"""Catch-up window widening (M5).

A rolling 7-day window forgives no long outage: if imports stop for 10 days, three
days fall out of every subsequent 7-day window and are lost until someone widens it
by hand. Firefly's hash-based duplicate detection absorbs any overlap, so widening
the window for a single run after a detected gap is safe.

Only *scheduled* runs are widened — a manual "run now" uses the config as written.
Widening is applied in-place to the config file and restored afterwards; writing a
``<name>.catchup.json`` copy would violate the no-extra-cleartext-copies rule.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime

from . import schedules
from .configstore import ConfigStore

# Hard ceiling below the PSD2 90-day limit; a second TAN mid-dialog beyond 90 days
# breaks the importer, so never widen to or past it.
MAX_CATCHUP_DAYS = 89
# Small overlap added on top of the observed gap; duplicate detection eats it.
OVERLAP_BUFFER_DAYS = 2


@dataclass(frozen=True, slots=True)
class CatchupPlan:
    original_raw: dict  # the full config dict as read from disk
    new_from: str       # the widened "from" expression, e.g. "now - 24 days"
    effective_days: int
    to_value: str | None


def _parse_iso(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def plan_catchup(conn, store: ConfigStore, config_name: str, trigger: str) -> CatchupPlan | None:
    """Decide whether to widen the window for this run. Returns None to leave it."""
    if trigger != "schedule":
        return None
    sched = schedules.get(conn, config_name)
    if sched is None or not sched.catchup_enabled:
        return None

    last = schedules.last_success_at(conn, config_name)
    if last is None:
        return None  # no prior success — nothing to catch up from

    try:
        cfg = store.read(config_name)
        raw = store.read_raw(config_name)
    except Exception:  # noqa: BLE001 — a broken config can't be safely widened
        return None

    today = date.today()
    current_span = cfg.choose_account_automation.window_span_days(today)
    days_since = (datetime.now(UTC) - _parse_iso(last)).days
    needed = days_since + OVERLAP_BUFFER_DAYS

    # Only widen if the gap exceeds what the current window already covers.
    if needed <= current_span:
        return None
    effective = min(needed, sched.catchup_max_days, MAX_CATCHUP_DAYS)
    if effective <= current_span:
        return None

    to_value = raw.get("choose_account_automation", {}).get("to")
    return CatchupPlan(
        original_raw=raw,
        new_from=f"now - {effective} days",
        effective_days=effective,
        to_value=to_value,
    )


def apply_plan(store: ConfigStore, config_name: str, plan: CatchupPlan) -> str:
    """Write the widened window to disk. Returns the original window block as JSON
    (no secrets — only iban/account id/from/to) for crash-repair bookkeeping."""
    original_block = plan.original_raw.get("choose_account_automation", {})
    mutated = dict(plan.original_raw)
    mutated["choose_account_automation"] = {**original_block, "from": plan.new_from}
    store.write_raw(config_name, mutated)
    return json.dumps(original_block)


def restore(store: ConfigStore, config_name: str, plan: CatchupPlan) -> None:
    """Restore the original config after a run (best-effort)."""
    store.write_raw(config_name, plan.original_raw)


def restore_from_block(store: ConfigStore, config_name: str, original_block_json: str) -> None:
    """Crash-repair restore: put the stored original window block back into whatever
    the config currently is (catch-up only ever mutated that block)."""
    block = json.loads(original_block_json)
    raw = store.read_raw(config_name)
    raw["choose_account_automation"] = block
    store.write_raw(config_name, raw)
