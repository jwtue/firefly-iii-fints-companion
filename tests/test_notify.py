"""Notification tests (M3): URL parsing, redaction, dispatch, dead-man switch."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app import schedules
from app.db import init_db
from app.notify.base import Message
from app.notify.dispatcher import Notifier, _estimate_interval_hours
from app.notify.ntfy import NtfyBackend
from app.notify.registry import build_backends
from app.notify.telegram import TelegramBackend
from app.redact import Redactor, set_active_redactor


@pytest.fixture
def conn():
    c = init_db(":memory:")
    yield c
    c.close()


class RecordingBackend:
    scheme = "recording"

    def __init__(self):
        self.sent: list[Message] = []

    async def send(self, message: Message) -> None:
        self.sent.append(message)


class FailingBackend:
    scheme = "failing"

    async def send(self, message: Message) -> None:
        raise RuntimeError("boom SECRET-IN-ERROR")


# --- URL parsing -------------------------------------------------------------

def test_ntfy_url_parsing():
    b = NtfyBackend("ntfy://ntfy.example/firefly")
    assert b._endpoint == "http://ntfy.example/firefly"
    b2 = NtfyBackend("ntfys://ntfy.example/topic")
    assert b2._endpoint == "https://ntfy.example/topic"


def test_telegram_url_parsing():
    b = TelegramBackend("tgram://123456:ABC/987654")
    assert b._token == "123456:ABC"
    assert b._chat_id == "987654"


def test_registry_builds_known_and_skips_unknown():
    backends = build_backends(
        ["ntfy://h/t", "tgram://tok/chat", "carrierpigeon://nope", "garbage"]
    )
    schemes = {b.scheme for b in backends}
    assert schemes == {"ntfy", "tgram"}


# --- dispatch + recording ----------------------------------------------------

async def test_notify_run_sends_once_and_marks_notified(conn):
    conn.execute(
        "INSERT INTO run (config_name, trigger, started_at, status, detection, error_header) "
        "VALUES ('giro.json', 'schedule', '2026-07-10T00:00:00+00:00', 'importer_error', 'heuristic', 'boom')"
    )
    run_id = conn.execute("SELECT id FROM run").fetchone()["id"]
    backend = RecordingBackend()
    notifier = Notifier(conn, [backend])

    await notifier.notify_run(run_id)
    await notifier.notify_run(run_id)  # second call must be a no-op

    assert len(backend.sent) == 1
    assert conn.execute("SELECT notified FROM run WHERE id = ?", (run_id,)).fetchone()["notified"] == 1
    # A notification row was recorded.
    assert conn.execute("SELECT COUNT(*) c FROM notification").fetchone()["c"] == 1


async def test_tan_required_uses_action_wording(conn):
    conn.execute(
        "INSERT INTO run (config_name, trigger, started_at, status, detection) "
        "VALUES ('giro.json', 'schedule', '2026-07-10T00:00:00+00:00', 'tan_required', 'heuristic')"
    )
    run_id = conn.execute("SELECT id FROM run").fetchone()["id"]
    backend = RecordingBackend()
    await Notifier(conn, [backend]).notify_run(run_id)
    msg = backend.sent[0]
    assert "ACTION NEEDED" in msg.title
    assert "persistence string" in msg.body


async def test_outbound_message_is_redacted(conn):
    secret = "PIN-SENTINEL-7777-abcdef"
    set_active_redactor(Redactor([secret]))
    try:
        conn.execute(
            "INSERT INTO run (config_name, trigger, started_at, status, detection, error_header) "
            "VALUES ('giro.json', 'schedule', '2026-07-10T00:00:00+00:00', 'importer_error', 'heuristic', ?)",
            (f"leaked {secret}",),
        )
        run_id = conn.execute("SELECT id FROM run").fetchone()["id"]
        backend = RecordingBackend()
        await Notifier(conn, [backend]).notify_run(run_id)
        assert secret not in backend.sent[0].body
    finally:
        set_active_redactor(Redactor())


async def test_failing_backend_records_redacted_error_and_does_not_raise(conn):
    set_active_redactor(Redactor(["SECRET-IN-ERROR"]))
    try:
        conn.execute(
            "INSERT INTO run (config_name, trigger, started_at, status, detection) "
            "VALUES ('giro.json', 'schedule', '2026-07-10T00:00:00+00:00', 'stalled', 'heuristic')"
        )
        run_id = conn.execute("SELECT id FROM run").fetchone()["id"]
        await Notifier(conn, [FailingBackend()]).notify_run(run_id)  # must not raise
        row = conn.execute("SELECT ok, error FROM notification").fetchone()
        assert row["ok"] == 0
        assert "SECRET-IN-ERROR" not in (row["error"] or "")
    finally:
        set_active_redactor(Redactor())


# --- dead-man's switch -------------------------------------------------------

def test_interval_estimate():
    assert _estimate_interval_hours("0 1 * * *") == 24.0      # daily
    assert _estimate_interval_hours("0 * * * *") == 1.0       # hourly
    assert _estimate_interval_hours("0 0 * * 1") == 24 * 7    # weekly
    assert _estimate_interval_hours("*/15 * * * *") == 1.0    # hour=* -> hourly-ish
    assert _estimate_interval_hours("bad") is None


async def test_deadman_alerts_when_overdue(conn):
    schedules.upsert(conn, "giro.json", enabled=True, cron="0 1 * * *")  # daily => threshold 48h
    old = (datetime.now(UTC) - timedelta(days=5)).isoformat()
    conn.execute(
        "INSERT INTO run (config_name, trigger, started_at, status, detection) VALUES "
        "('giro.json', 'schedule', ?, 'ok', 'heuristic')",
        (old,),
    )
    backend = RecordingBackend()
    notifier = Notifier(conn, [backend])
    await notifier.check_deadman()
    assert len(backend.sent) == 1
    assert "STUCK" in backend.sent[0].title
    # Idempotent for the same stale reference.
    await notifier.check_deadman()
    assert len(backend.sent) == 1


async def test_deadman_quiet_when_recent(conn):
    schedules.upsert(conn, "giro.json", enabled=True, cron="0 1 * * *")
    recent = (datetime.now(UTC) - timedelta(hours=6)).isoformat()
    conn.execute(
        "INSERT INTO run (config_name, trigger, started_at, status, detection) VALUES "
        "('giro.json', 'schedule', ?, 'ok', 'heuristic')",
        (recent,),
    )
    backend = RecordingBackend()
    await Notifier(conn, [backend]).check_deadman()
    assert backend.sent == []
