"""Notifier: turn a run outcome into messages, redact, send, record.

This is the M3 hook the runner calls on failure. It also hosts the dead-man's
switch: a periodic check that alerts when a scheduled config has not succeeded for
longer than twice its interval — the failure mode where the sidecar itself is stuck
and no per-run failure ever fires.

Every outbound message body passes through the process-wide redactor here, so a
leaked secret in an importer error can never reach a notification channel.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime

from ..importer.status import RunStatus
from ..redact import redact
from .base import Message, NotifyBackend

logger = logging.getLogger("sidecar.notify")

# Human wording per status, with special care for the TAN cases (they need a
# person to act via the importer UI, not a bug fix).
_STATUS_WORDING: dict[str, str] = {
    RunStatus.TAN_REQUIRED: (
        "The bank asked for a TAN. A headless run can't answer it — log in through "
        "the importer UI once, complete the TAN, then paste the new persistence "
        "string into the sidecar. PSD2 forces this roughly every 90 days."
    ),
    RunStatus.TAN_DEVICE_AMBIGUOUS: (
        "The bank offers several TAN media but the config doesn't name one "
        "(bank_2fa_device). Set it to a device name the importer UI lists after login."
    ),
    RunStatus.CONFIG_NOT_FOUND: "The importer could not find this configuration file.",
    RunStatus.VERIFICATION_FAILED: "The configured IBAN or Firefly account id did not match.",
    RunStatus.IMPORTER_ERROR: "The importer reported an error.",
    RunStatus.STALLED: "The run ended on an unrecognized importer page (a silent stall).",
    RunStatus.TIMEOUT: "The importer did not respond in time.",
    RunStatus.UNREACHABLE: "The importer could not be reached.",
    RunStatus.INTERNAL_ERROR: "The sidecar hit an internal error while running this import.",
}


class Notifier:
    def __init__(self, conn: sqlite3.Connection, backends: list[NotifyBackend]):
        self.conn = conn
        self.backends = backends

    @property
    def enabled(self) -> bool:
        return bool(self.backends)

    # --- per-run failure -----------------------------------------------------

    async def notify_run(self, run_id: int) -> None:
        row = self.conn.execute("SELECT * FROM run WHERE id = ?", (run_id,)).fetchone()
        if row is None or row["notified"]:
            return
        status = RunStatus(row["status"])
        message = self._build_run_message(row, status)
        await self._dispatch(message, run_id=run_id)
        self.conn.execute("UPDATE run SET notified = 1 WHERE id = ?", (run_id,))

    def _build_run_message(self, row, status: RunStatus) -> Message:
        needs_action = status.needs_tan
        prefix = "ACTION NEEDED" if needs_action else "FAILED"
        title = f"[{prefix}] FinTS import {row['config_name']}"
        explanation = _STATUS_WORDING.get(status, f"Status: {status.value}")
        parts = [
            explanation,
            "",
            f"Config: {row['config_name']}",
            f"Status: {status.value}",
            f"When: {row['started_at']}",
        ]
        if row["error_header"]:
            parts.append(f"Detail: {row['error_header']}")
        # error_header is already redacted at storage time; redact again defensively.
        body = redact("\n".join(parts)) or ""
        return Message(title=title, body=body, priority=2 if needs_action else 1)

    # --- dead-man's switch ---------------------------------------------------

    async def check_deadman(self) -> None:
        """Alert on schedules whose last success is older than 2× their interval.

        Uses a coarse interval estimate from the cron's typical cadence — good
        enough to catch "nothing has succeeded in ages". Sends at most one alert
        per config per stale period by keying on a synthetic audit marker.
        """
        from .. import schedules

        now = datetime.now(UTC)
        for sched in schedules.list_enabled(self.conn):
            interval_hours = _estimate_interval_hours(sched.cron)
            if interval_hours is None:
                continue
            last = schedules.last_success_at(self.conn, sched.config_name)
            threshold_hours = 2 * interval_hours
            if last is None:
                # Never succeeded while scheduled — only warn once we're well past
                # one interval since the schedule was set.
                reference = sched.updated_at
            else:
                reference = last
            age_hours = (now - _parse(reference)).total_seconds() / 3600
            if age_hours <= threshold_hours:
                continue
            if self._already_alerted(sched.config_name, reference):
                continue
            title = f"[STUCK] FinTS import {sched.config_name}"
            body = redact(
                f"No successful import of {sched.config_name} for {age_hours:.0f}h "
                f"(schedule runs about every {interval_hours:.0f}h). The importer or "
                f"the sidecar may be stuck, or a TAN is overdue."
            ) or ""
            await self._dispatch(Message(title=title, body=body, priority=2))
            self._mark_alerted(sched.config_name, reference)

    def _already_alerted(self, config_name: str, reference: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM audit WHERE action = 'deadman.alert' AND target = ? AND detail = ?",
            (config_name, reference),
        ).fetchone()
        return row is not None

    def _mark_alerted(self, config_name: str, reference: str) -> None:
        self.conn.execute(
            "INSERT INTO audit (at, actor, action, target, detail) VALUES (?, 'system', 'deadman.alert', ?, ?)",
            (datetime.now(UTC).isoformat(), config_name, reference),
        )

    # --- shared send ---------------------------------------------------------

    async def _dispatch(self, message: Message, *, run_id: int | None = None) -> None:
        if not self.backends:
            logger.info("no notify backends configured; would have sent: %s", message.title)
            return
        for backend in self.backends:
            ok = True
            error = None
            try:
                await backend.send(message)
            except Exception as exc:  # noqa: BLE001 — one backend failing must not stop others
                ok = False
                error = redact(str(exc))
                logger.error("notify backend %s failed: %s", backend.scheme, error)
            self.conn.execute(
                "INSERT INTO notification (run_id, backend, sent_at, ok, error) "
                "VALUES (?, ?, ?, ?, ?)",
                (run_id, backend.scheme, datetime.now(UTC).isoformat(), int(ok), error),
            )

    async def send_test(self) -> None:
        await self._dispatch(Message(
            title="[TEST] FinTS Sidecar",
            body="This is a test notification from the FinTS sidecar. If you see it, alerts work.",
            priority=1,
        ))


def _parse(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _estimate_interval_hours(cron: str) -> float | None:
    """Very rough cadence estimate from a 5-field cron, for the dead-man threshold.

    Only needs to distinguish hourly-ish from daily-ish from weekly-ish; exactness
    doesn't matter because the threshold is 2× and we just want "way overdue".
    """
    fields = cron.split()
    if len(fields) != 5:
        return None
    minute, hour, dom, month, dow = fields
    if dow != "*" and dom == "*":
        return 24 * 7  # weekly-ish
    if hour == "*":
        return 1  # hourly-ish
    if hour.startswith("*/"):
        try:
            return float(hour[2:])
        except ValueError:
            return 24.0
    return 24.0  # daily-ish default
