"""Catch-up window widening (M5) and crash repair."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app import catchup, schedules
from app.configstore import ConfigStore
from app.db import init_db
from app.importer.client import ImporterClient
from app.models import FintsConfig
from app.runner import Runner, repair_crashed_runs

from .stub.importer import app as stub_app
from .test_models import base_config


@pytest.fixture
def conn():
    c = init_db(":memory:")
    yield c
    c.close()


@pytest.fixture
def store(tmp_path):
    return ConfigStore(tmp_path)


def seed(store, name="ok.json", from_expr="now - 7 days"):
    cfg = FintsConfig.model_validate(
        base_config(choose_account_automation={"from": from_expr, "to": "now"})
    )
    store.write(name, cfg)


def make_runner(conn, store):
    transport = httpx.ASGITransport(app=stub_app)
    client = ImporterClient("http://stub", timeout_seconds=5.0, transport=transport)
    return Runner(conn, store, client)


def record_success(conn, name, days_ago):
    ts = (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()
    conn.execute(
        "INSERT INTO run (config_name, trigger, started_at, status, detection) "
        "VALUES (?, 'schedule', ?, 'ok', 'heuristic')",
        (name, ts),
    )


# --- plan_catchup ------------------------------------------------------------

def test_no_widening_for_manual_trigger(conn, store):
    seed(store)
    schedules.upsert(conn, "ok.json", enabled=True, cron="0 1 * * *")
    record_success(conn, "ok.json", days_ago=20)
    assert catchup.plan_catchup(conn, store, "ok.json", "manual") is None


def test_no_widening_without_schedule(conn, store):
    seed(store)
    record_success(conn, "ok.json", days_ago=20)
    assert catchup.plan_catchup(conn, store, "ok.json", "schedule") is None


def test_no_widening_when_within_window(conn, store):
    seed(store, from_expr="now - 7 days")
    schedules.upsert(conn, "ok.json", enabled=True, cron="0 1 * * *")
    record_success(conn, "ok.json", days_ago=3)  # gap 3 < span 7
    assert catchup.plan_catchup(conn, store, "ok.json", "schedule") is None


def test_widening_after_outage(conn, store):
    seed(store, from_expr="now - 7 days")
    schedules.upsert(conn, "ok.json", enabled=True, cron="0 1 * * *", catchup_max_days=60)
    record_success(conn, "ok.json", days_ago=20)  # gap 20 > span 7
    plan = catchup.plan_catchup(conn, store, "ok.json", "schedule")
    assert plan is not None
    assert plan.effective_days == 22  # 20 + 2 buffer
    assert plan.new_from == "now - 22 days"


def test_widening_capped_at_catchup_max(conn, store):
    seed(store, from_expr="now - 7 days")
    schedules.upsert(conn, "ok.json", enabled=True, cron="0 1 * * *", catchup_max_days=30)
    record_success(conn, "ok.json", days_ago=200)
    plan = catchup.plan_catchup(conn, store, "ok.json", "schedule")
    assert plan.effective_days == 30  # capped by catchup_max_days


def test_widening_never_exceeds_psd2_ceiling(conn, store):
    seed(store, from_expr="now - 7 days")
    schedules.upsert(conn, "ok.json", enabled=True, cron="0 1 * * *", catchup_max_days=89)
    record_success(conn, "ok.json", days_ago=200)
    plan = catchup.plan_catchup(conn, store, "ok.json", "schedule")
    assert plan.effective_days <= 89


def test_disabled_catchup_no_widening(conn, store):
    seed(store)
    schedules.upsert(conn, "ok.json", enabled=True, cron="0 1 * * *", catchup_enabled=False)
    record_success(conn, "ok.json", days_ago=20)
    assert catchup.plan_catchup(conn, store, "ok.json", "schedule") is None


# --- apply / restore round trip ----------------------------------------------

def test_apply_and_restore_leaves_config_unchanged(conn, store):
    seed(store, from_expr="now - 7 days")
    before = store.read_raw("ok.json")
    plan = catchup.CatchupPlan(
        original_raw=before, new_from="now - 22 days", effective_days=22, to_value="now"
    )
    original_block = catchup.apply_plan(store, "ok.json", plan)
    widened = store.read_raw("ok.json")
    assert widened["choose_account_automation"]["from"] == "now - 22 days"
    assert json.loads(original_block)["from"] == "now - 7 days"
    catchup.restore(store, "ok.json", plan)
    assert store.read_raw("ok.json") == before


# --- runner integration ------------------------------------------------------

async def test_run_records_effective_window_and_restores(conn, store):
    seed(store, name="ok.json", from_expr="now - 7 days")
    schedules.upsert(conn, "ok.json", enabled=True, cron="0 1 * * *")
    record_success(conn, "ok.json", days_ago=20)

    runner = make_runner(conn, store)
    result = await runner.execute("ok.json", "schedule")

    row = conn.execute("SELECT * FROM run WHERE id = ?", (result.run_id,)).fetchone()
    assert row["window_from"] == "now - 22 days"
    assert row["window_original"] is not None
    # Config file was restored after the run.
    assert store.read_raw("ok.json")["choose_account_automation"]["from"] == "now - 7 days"


# --- crash repair ------------------------------------------------------------

def test_repair_marks_running_as_internal_error_and_restores(conn, store):
    seed(store, name="ok.json", from_expr="now - 7 days")
    # Simulate a crash mid-catch-up: config left widened, run left 'running'.
    original_block = json.dumps({
        "bank_account_iban": "DE00600501010000000000",
        "firefly_account_id": 3,
        "from": "now - 7 days",
        "to": "now",
    })
    raw = store.read_raw("ok.json")
    raw["choose_account_automation"]["from"] = "now - 22 days"
    store.write_raw("ok.json", raw)
    conn.execute(
        "INSERT INTO run (config_name, trigger, started_at, status, detection, window_original) "
        "VALUES ('ok.json', 'schedule', '2026-07-10T00:00:00+00:00', 'running', 'heuristic', ?)",
        (original_block,),
    )

    repaired = repair_crashed_runs(conn, store)
    assert repaired == 1
    row = conn.execute("SELECT status FROM run WHERE config_name = 'ok.json'").fetchone()
    assert row["status"] == "internal_error"
    # The widened window was rolled back.
    assert store.read_raw("ok.json")["choose_account_automation"]["from"] == "now - 7 days"
