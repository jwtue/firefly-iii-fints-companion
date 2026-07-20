"""SQLite persistence — run history, schedules, notifications, audit.

No secrets are stored here. Configs live only as JSON on the shared volume
(AGENTS.md §6: no extra cleartext copies). The DB holds run outcomes (with the
response body already redacted by the runner), schedules and an audit trail.

Migrations are a simple ordered list keyed on the ``schema_version`` table; each
runs once inside a transaction.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# Ordered migrations. Append-only; never edit a shipped one.
_MIGRATIONS: list[str] = [
    # v1 — initial schema
    """
    CREATE TABLE run (
      id                INTEGER PRIMARY KEY AUTOINCREMENT,
      config_name       TEXT    NOT NULL,
      trigger           TEXT    NOT NULL CHECK(trigger IN ('schedule','manual','catchup')),
      started_at        TEXT    NOT NULL,
      finished_at       TEXT,
      duration_ms       INTEGER,
      status            TEXT    NOT NULL CHECK(status IN (
                          'running','ok','ok_no_transactions','tan_required',
                          'tan_device_ambiguous','config_not_found','verification_failed',
                          'importer_error','stalled','timeout','unreachable','internal_error')),
      detection         TEXT    NOT NULL CHECK(detection IN ('json','http_status','heuristic')),
      http_status       INTEGER,
      transactions_sent INTEGER,
      error_header      TEXT,
      error_message     TEXT,
      response_body     TEXT,
      response_bytes    INTEGER,
      window_from       TEXT,
      window_to         TEXT,
      window_original   TEXT,
      notified          INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX ix_run_config_started ON run(config_name, started_at DESC);
    CREATE INDEX ix_run_started        ON run(started_at DESC);

    CREATE TABLE schedule (
      config_name      TEXT PRIMARY KEY,
      enabled          INTEGER NOT NULL DEFAULT 0,
      cron             TEXT    NOT NULL,
      timezone         TEXT    NOT NULL DEFAULT 'Europe/Berlin',
      catchup_enabled  INTEGER NOT NULL DEFAULT 1,
      catchup_max_days INTEGER NOT NULL DEFAULT 60,
      last_success_at  TEXT,
      updated_at       TEXT    NOT NULL
    );

    CREATE TABLE notification (
      id       INTEGER PRIMARY KEY AUTOINCREMENT,
      run_id   INTEGER REFERENCES run(id) ON DELETE CASCADE,
      backend  TEXT    NOT NULL,
      sent_at  TEXT    NOT NULL,
      ok       INTEGER NOT NULL,
      error    TEXT
    );

    CREATE TABLE audit (
      id     INTEGER PRIMARY KEY AUTOINCREMENT,
      at     TEXT NOT NULL,
      actor  TEXT NOT NULL,
      action TEXT NOT NULL,
      target TEXT,
      detail TEXT
    );
    """,
]


def connect(db_path: Path | str) -> sqlite3.Connection:
    """Open a connection with the pragmas this app relies on.

    ``check_same_thread=False`` because APScheduler jobs and request handlers touch
    the same connection pool across threads; writes are serialized by the run lock
    and by SQLite's own locking.
    """
    conn = sqlite3.connect(
        db_path,
        check_same_thread=False,
        isolation_level=None,  # autocommit; we manage transactions explicitly
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _current_version(conn: sqlite3.Connection) -> int:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    return row["v"] or 0


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending migrations. Returns the resulting schema version."""
    version = _current_version(conn)
    for i, sql in enumerate(_MIGRATIONS, start=1):
        if i <= version:
            continue
        # executescript() implicitly commits any open transaction, so it manages
        # its own atomicity; we record the version immediately after it succeeds.
        conn.executescript(sql)
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (i,))
        version = i
    return version


def init_db(db_path: Path | str) -> sqlite3.Connection:
    """Connect, ensure the parent dir exists, and run migrations."""
    path = Path(db_path)
    if path.name != ":memory:" and str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    migrate(conn)
    return conn
