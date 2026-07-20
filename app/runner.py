"""Execute an importer run and persist a fully-classified, redacted result.

Flow: acquire the global run lock → trigger the importer → classify the response
via the detector chain → redact the body and error text → insert a ``run`` row.

The lock is module-global and every path (manual "Run now" and scheduled) goes
through it, so runs never overlap against the same bank. Catch-up window widening
(M5) and notifications (M3) hook into the marked points but are no-ops for now.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from . import catchup, schedules
from .configstore import ConfigStore
from .importer.client import ImporterClient
from .importer.detect import DEFAULT_CHAIN, detect
from .importer.status import RunOutcome, RunStatus
from .redact import redact

logger = logging.getLogger("sidecar.runner")

# Global serialization lock. Manual and scheduled runs share it so exactly one run
# touches the importer at a time.
RUN_LOCK = asyncio.Lock()

# Response bodies are stored redacted and truncated. 64 KiB is plenty to diagnose
# a failure without unbounded growth.
MAX_BODY_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class RunResult:
    run_id: int
    status: RunStatus


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _prepare_body(body: str | None) -> tuple[str | None, int | None]:
    """Redact, strip active content, and truncate a response body for storage."""
    if body is None:
        return None, None
    original_bytes = len(body.encode("utf-8", errors="replace"))
    cleaned = redact(body) or ""
    # Drop script/style blocks so a stored body can't run anything if ever mis-rendered.
    import re

    cleaned = re.sub(r"(?is)<(script|style)\b.*?</\1>", "", cleaned)
    if len(cleaned.encode("utf-8")) > MAX_BODY_BYTES:
        cleaned = cleaned.encode("utf-8")[:MAX_BODY_BYTES].decode("utf-8", errors="ignore")
        cleaned += "\n… [truncated]"
    return cleaned, original_bytes


class Runner:
    def __init__(
        self,
        conn: sqlite3.Connection,
        store: ConfigStore,
        client: ImporterClient,
        notifier=None,
    ):
        self.conn = conn
        self.store = store
        self.client = client
        # Set after construction once the notifier is built (M3). None => no alerts.
        self.notifier = notifier

    async def execute(self, config_name: str, trigger: str) -> RunResult:
        """Run one import. ``trigger`` is 'manual' | 'schedule' | 'catchup'."""
        async with RUN_LOCK:
            return await self._execute_locked(config_name, trigger)

    async def _execute_locked(self, config_name: str, trigger: str) -> RunResult:
        started = _now_iso()
        t0 = time.monotonic()

        # M5: widen the window in-place after a detected outage (scheduled runs
        # only). window_original is stored so a crash mid-run is repairable.
        plan = catchup.plan_catchup(self.conn, self.store, config_name, trigger)
        window_from = window_to = window_original = None
        if plan is not None:
            window_original = catchup.apply_plan(self.store, config_name, plan)
            window_from = plan.new_from
            window_to = plan.to_value
            logger.info(
                "catch-up: widened %s to '%s' (%d days)",
                config_name, plan.new_from, plan.effective_days,
            )

        run_id = self._insert_running(
            config_name, trigger, started, window_from, window_to, window_original
        )

        try:
            try:
                result = await self.client.trigger(config_name)
                if result.response is not None:
                    outcome = detect(result.response, DEFAULT_CHAIN)
                    body, body_bytes = _prepare_body(result.response.text)
                    http_status = result.response.status_code
                else:
                    outcome = RunOutcome(
                        result.transport_status or RunStatus.INTERNAL_ERROR,
                        "heuristic",
                        error_header="Importer call did not return a response",
                        error_message=result.transport_error,
                    )
                    body, body_bytes = None, None
                    http_status = None
            except Exception as exc:  # noqa: BLE001 — never let a run crash the process
                outcome = RunOutcome(
                    RunStatus.INTERNAL_ERROR,
                    "heuristic",
                    error_header="Sidecar error while handling the run",
                    error_message=redact(repr(exc)),
                )
                body, body_bytes, http_status = None, None, None

            duration_ms = int((time.monotonic() - t0) * 1000)
            self._finalize(
                run_id,
                outcome=outcome,
                body=body,
                body_bytes=body_bytes,
                http_status=http_status,
                duration_ms=duration_ms,
            )

            # M2: keep the schedule's last-success cache current for the dead-man's
            # switch and the dashboard.
            if outcome.status.is_success:
                schedules.set_last_success(self.conn, config_name, started)

            # M3: notify on failure. The notifier marks the run row as notified so a
            # repeated failure of the same config isn't re-sent every run.
            if outcome.status.is_failure and self.notifier is not None:
                await self.notifier.notify_run(run_id)

            return RunResult(run_id, outcome.status)
        finally:
            # M5: always restore the original window, even on cancellation.
            if plan is not None:
                try:
                    catchup.restore(self.store, config_name, plan)
                except Exception:  # noqa: BLE001
                    logger.exception("failed to restore catch-up window for %s", config_name)

    # --- persistence ---------------------------------------------------------

    def _insert_running(
        self, config_name, trigger, started, window_from, window_to, window_original
    ) -> int:
        cur = self.conn.execute(
            """INSERT INTO run
                 (config_name, trigger, started_at, status, detection,
                  window_from, window_to, window_original)
               VALUES (?, ?, ?, 'running', 'heuristic', ?, ?, ?)""",
            (config_name, trigger, started, window_from, window_to, window_original),
        )
        return int(cur.lastrowid)

    def _finalize(self, run_id, *, outcome, body, body_bytes, http_status, duration_ms) -> None:
        self.conn.execute(
            """UPDATE run SET
                 finished_at = ?, duration_ms = ?, status = ?, detection = ?,
                 http_status = ?, transactions_sent = ?, error_header = ?,
                 error_message = ?, response_body = ?, response_bytes = ?
               WHERE id = ?""",
            (
                _now_iso(),
                duration_ms,
                str(outcome.status),
                outcome.detection,
                http_status,
                outcome.transactions_sent,
                redact(outcome.error_header),
                redact(outcome.error_message),
                body,
                body_bytes,
                run_id,
            ),
        )


def repair_crashed_runs(conn: sqlite3.Connection, store: ConfigStore) -> int:
    """Startup repair (M5): reconcile runs left in 'running' by a crash/restart.

    For each stuck run, restore the catch-up window if one was applied (using the
    stored ``window_original`` block) and mark the run ``internal_error``. Returns
    the number of runs repaired.
    """
    stuck = conn.execute(
        "SELECT id, config_name, window_original FROM run WHERE status = 'running'"
    ).fetchall()
    for row in stuck:
        if row["window_original"]:
            try:
                catchup.restore_from_block(store, row["config_name"], row["window_original"])
            except Exception:  # noqa: BLE001 — repair must not block startup
                logger.exception(
                    "could not restore catch-up window for %s during crash repair",
                    row["config_name"],
                )
        conn.execute(
            "UPDATE run SET status = 'internal_error', finished_at = ?, "
            "error_header = 'Run interrupted by restart' WHERE id = ?",
            (_now_iso(), row["id"]),
        )
    if stuck:
        logger.warning("repaired %d run(s) left running after a restart", len(stuck))
    return len(stuck)
