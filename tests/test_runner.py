"""Integration tests for the runner against the in-process stub importer."""

from __future__ import annotations

import httpx
import pytest

from app.configstore import ConfigStore
from app.db import init_db
from app.importer.client import ImporterClient
from app.importer.status import RunStatus
from app.runner import Runner

from .stub.importer import app as stub_app


@pytest.fixture
def conn():
    c = init_db(":memory:")
    yield c
    c.close()


@pytest.fixture
def store(tmp_path):
    return ConfigStore(tmp_path)


def make_runner(conn, store) -> Runner:
    transport = httpx.ASGITransport(app=stub_app)
    client = ImporterClient("http://stub", timeout_seconds=5.0, transport=transport)
    return Runner(conn, store, client)


async def test_successful_run_is_recorded(conn, store):
    runner = make_runner(conn, store)
    result = await runner.execute("ok.json", "manual")
    assert result.status is RunStatus.OK
    row = conn.execute("SELECT * FROM run WHERE id = ?", (result.run_id,)).fetchone()
    assert row["status"] == "ok"
    assert row["transactions_sent"] == 12
    assert row["finished_at"] is not None
    assert row["trigger"] == "manual"


async def test_config_not_found_is_failure(conn, store):
    runner = make_runner(conn, store)
    result = await runner.execute("missing.json", "manual")
    assert result.status is RunStatus.CONFIG_NOT_FOUND
    assert result.status.is_failure


async def test_unmapped_config_is_stalled_not_ok(conn, store):
    """The regression guard: an unrecognized importer page (here: the setup list
    the stub falls back to) must be a failure, never a silent OK."""
    runner = make_runner(conn, store)
    result = await runner.execute("does-not-exist.json", "manual")
    assert result.status is RunStatus.STALLED
    assert result.status.is_failure


async def test_tan_required_recorded(conn, store):
    runner = make_runner(conn, store)
    result = await runner.execute("tan.json", "manual")
    assert result.status is RunStatus.TAN_REQUIRED
    assert result.status.needs_tan


async def test_response_body_is_redacted_before_storage(conn, store, monkeypatch):
    """Seed a secret, serve a body containing it, assert it never reaches the DB."""
    from app.redact import Redactor, set_active_redactor

    secret = "PIN-SENTINEL-9999-abcdefghij"
    set_active_redactor(Redactor([secret]))

    # Serve a body embedding the secret by pointing the stub at a crafted response.
    async def fake_trigger(config_name):
        from app.importer.client import TriggerResult

        resp = httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text=f"<b>Fatal error</b>: leaked bank_password={secret}",
            request=httpx.Request("GET", "http://stub/"),
        )
        return TriggerResult(response=resp, transport_status=None)

    runner = make_runner(conn, store)
    monkeypatch.setattr(runner.client, "trigger", fake_trigger)
    result = await runner.execute("fatal.json", "manual")

    row = conn.execute("SELECT * FROM run WHERE id = ?", (result.run_id,)).fetchone()
    assert result.status is RunStatus.IMPORTER_ERROR
    for col in ("response_body", "error_header", "error_message"):
        assert secret not in (row[col] or "")
    set_active_redactor(Redactor())


async def test_timeout_is_classified(conn, store, monkeypatch):
    from app.importer.client import TriggerResult

    async def timing_out(config_name):
        return TriggerResult(None, RunStatus.TIMEOUT, "importer timed out")

    runner = make_runner(conn, store)
    monkeypatch.setattr(runner.client, "trigger", timing_out)
    result = await runner.execute("ok.json", "manual")
    assert result.status is RunStatus.TIMEOUT


async def test_runs_are_serialized_by_the_lock(conn, store):
    """Two concurrent executes must not overlap (same bank, one at a time)."""
    import asyncio

    from app import runner as runner_mod

    order: list[str] = []
    orig = runner_mod.Runner._execute_locked

    async def traced(self, config_name, trigger):
        order.append(f"start:{config_name}")
        await asyncio.sleep(0.05)
        order.append(f"end:{config_name}")
        return await orig(self, config_name, trigger)

    runner_mod.Runner._execute_locked = traced
    try:
        runner = make_runner(conn, store)
        await asyncio.gather(
            runner.execute("ok.json", "manual"),
            runner.execute("tan.json", "schedule"),
        )
    finally:
        runner_mod.Runner._execute_locked = orig

    # The second run's start must come after the first run's end — no interleave.
    assert order[0].startswith("start:")
    assert order[1].startswith("end:")
    assert order[2].startswith("start:")
    assert order[3].startswith("end:")
