"""Scheduler tests (M2): reconcile, no-run-at-startup, orphan pruning."""

from __future__ import annotations

import asyncio

import pytest

from app import schedules
from app.db import init_db
from app.scheduler import SchedulerService


@pytest.fixture
def conn():
    c = init_db(":memory:")
    yield c
    c.close()


async def test_no_job_fires_shortly_after_startup(conn):
    """A '* * * * *' schedule (every minute) must NOT fire in the first seconds
    after start — reconcile never assigns an immediate next-run time. This is the
    guard against a redeploy triggering a bank login."""
    fired: list[str] = []

    async def run_cb(name, trigger):
        fired.append(name)

    schedules.upsert(conn, "giro.json", enabled=True, cron="* * * * *")
    svc = SchedulerService(run_cb)
    svc.reconcile(conn)
    svc.start()
    try:
        await asyncio.sleep(1.5)
    finally:
        svc.shutdown()
    assert fired == []
    # But a job WAS scheduled, with a future next-run time.
    assert "giro.json" in svc.next_run_times()


async def test_reconcile_adds_only_enabled(conn):
    async def run_cb(name, trigger):
        pass

    schedules.upsert(conn, "on.json", enabled=True, cron="0 1 * * *")
    schedules.upsert(conn, "off.json", enabled=False, cron="0 1 * * *")
    svc = SchedulerService(run_cb)
    svc.reconcile(conn)
    svc.start()
    try:
        jobs = {j.id for j in svc._scheduler.get_jobs()}
    finally:
        svc.shutdown()
    assert "run:on.json" in jobs
    assert "run:off.json" not in jobs


async def test_reconcile_removes_disabled_job(conn):
    async def run_cb(name, trigger):
        pass

    schedules.upsert(conn, "giro.json", enabled=True, cron="0 1 * * *")
    svc = SchedulerService(run_cb)
    svc.reconcile(conn)
    svc.start()
    try:
        assert "run:giro.json" in {j.id for j in svc._scheduler.get_jobs()}
        # Disable and reconcile again.
        schedules.upsert(conn, "giro.json", enabled=False, cron="0 1 * * *")
        svc.reconcile(conn)
        assert "run:giro.json" not in {j.id for j in svc._scheduler.get_jobs()}
    finally:
        svc.shutdown()


async def test_invalid_cron_is_skipped_not_fatal(conn):
    async def run_cb(name, trigger):
        pass

    schedules.upsert(conn, "bad.json", enabled=True, cron="not a cron")
    svc = SchedulerService(run_cb)
    svc.reconcile(conn)  # must not raise
    svc.start()
    try:
        assert "run:bad.json" not in {j.id for j in svc._scheduler.get_jobs()}
    finally:
        svc.shutdown()


def test_prune_orphans_removes_missing_configs(conn):
    schedules.upsert(conn, "gone.json", enabled=True, cron="0 1 * * *")
    schedules.upsert(conn, "here.json", enabled=True, cron="0 1 * * *")
    removed = schedules.prune_orphans(conn, {"here.json"})
    assert removed == ["gone.json"]
    assert schedules.get(conn, "gone.json") is None
    assert schedules.get(conn, "here.json") is not None


def test_last_success_read_from_run_table(conn):
    conn.execute(
        "INSERT INTO run (config_name, trigger, started_at, status, detection) "
        "VALUES ('giro.json', 'manual', '2026-07-01T00:00:00+00:00', 'ok', 'heuristic')"
    )
    conn.execute(
        "INSERT INTO run (config_name, trigger, started_at, status, detection) "
        "VALUES ('giro.json', 'manual', '2026-07-10T00:00:00+00:00', 'importer_error', 'heuristic')"
    )
    # Latest SUCCESS wins, not the latest run.
    assert schedules.last_success_at(conn, "giro.json") == "2026-07-01T00:00:00+00:00"
