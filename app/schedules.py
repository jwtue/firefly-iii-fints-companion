"""Schedule persistence — one optional cron schedule per config.

The JSON config files are the source of truth for *which* configs exist; this
table only adds scheduling metadata keyed by config name. `reconcile()` (in
``scheduler.py``) drops rows whose config file has disappeared.

"Last success" is derived from the ``run`` table (the real record of what
happened); ``schedule.last_success_at`` is kept updated as a convenience cache for
the dead-man's-switch and the dashboard.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class Schedule:
    config_name: str
    enabled: bool
    cron: str
    timezone: str
    catchup_enabled: bool
    catchup_max_days: int
    last_success_at: str | None
    updated_at: str


def _row_to_schedule(row: sqlite3.Row) -> Schedule:
    return Schedule(
        config_name=row["config_name"],
        enabled=bool(row["enabled"]),
        cron=row["cron"],
        timezone=row["timezone"],
        catchup_enabled=bool(row["catchup_enabled"]),
        catchup_max_days=int(row["catchup_max_days"]),
        last_success_at=row["last_success_at"],
        updated_at=row["updated_at"],
    )


def get(conn: sqlite3.Connection, config_name: str) -> Schedule | None:
    row = conn.execute(
        "SELECT * FROM schedule WHERE config_name = ?", (config_name,)
    ).fetchone()
    return _row_to_schedule(row) if row else None


def list_all(conn: sqlite3.Connection) -> list[Schedule]:
    rows = conn.execute("SELECT * FROM schedule ORDER BY config_name").fetchall()
    return [_row_to_schedule(r) for r in rows]


def list_enabled(conn: sqlite3.Connection) -> list[Schedule]:
    rows = conn.execute(
        "SELECT * FROM schedule WHERE enabled = 1 ORDER BY config_name"
    ).fetchall()
    return [_row_to_schedule(r) for r in rows]


def upsert(
    conn: sqlite3.Connection,
    config_name: str,
    *,
    enabled: bool,
    cron: str,
    timezone: str = "Europe/Berlin",
    catchup_enabled: bool = True,
    catchup_max_days: int = 60,
) -> None:
    now = datetime.now(UTC).isoformat()
    conn.execute(
        """INSERT INTO schedule
             (config_name, enabled, cron, timezone, catchup_enabled, catchup_max_days, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(config_name) DO UPDATE SET
             enabled = excluded.enabled,
             cron = excluded.cron,
             timezone = excluded.timezone,
             catchup_enabled = excluded.catchup_enabled,
             catchup_max_days = excluded.catchup_max_days,
             updated_at = excluded.updated_at""",
        (config_name, int(enabled), cron, timezone, int(catchup_enabled),
         int(catchup_max_days), now),
    )


def delete(conn: sqlite3.Connection, config_name: str) -> None:
    conn.execute("DELETE FROM schedule WHERE config_name = ?", (config_name,))


def prune_orphans(conn: sqlite3.Connection, existing_config_names: set[str]) -> list[str]:
    """Delete schedule rows whose config file no longer exists. Returns removed names."""
    removed = [
        r["config_name"]
        for r in conn.execute("SELECT config_name FROM schedule").fetchall()
        if r["config_name"] not in existing_config_names
    ]
    for name in removed:
        delete(conn, name)
    return removed


def set_last_success(conn: sqlite3.Connection, config_name: str, when_iso: str) -> None:
    """Update the convenience cache. No-op if the config has no schedule row."""
    conn.execute(
        "UPDATE schedule SET last_success_at = ? WHERE config_name = ?",
        (when_iso, config_name),
    )


def last_success_at(conn: sqlite3.Connection, config_name: str) -> str | None:
    """Authoritative last-success timestamp, read from the run table."""
    row = conn.execute(
        "SELECT MAX(started_at) AS ts FROM run "
        "WHERE config_name = ? AND status IN ('ok','ok_no_transactions')",
        (config_name,),
    ).fetchone()
    return row["ts"] if row else None
