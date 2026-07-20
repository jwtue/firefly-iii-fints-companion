"""Config editor tests (M4): secret preservation, validation, regex audit, CRUD."""

from __future__ import annotations

import json

import httpx
import pytest

from app.configstore import ConfigStore
from app.importer.client import ImporterClient
from app.main import create_app
from app.models import FintsConfig
from app.settings import Settings

from .stub.importer import app as stub_app
from .test_models import base_config


def build_app(tmp_path):
    settings = Settings(
        config_dir=tmp_path / "configs",
        state_dir=tmp_path / "state",
        trusted_networks=["10.0.0.0/8"],
    )
    settings.validate_auth()
    app = create_app(settings)
    app.state.ctx.client = ImporterClient(
        "http://stub", timeout_seconds=5.0, transport=httpx.ASGITransport(app=stub_app)
    )
    return app


def seed(tmp_path, name="giro.json", **overrides):
    ConfigStore(tmp_path / "configs").write(
        name, FintsConfig.model_validate(base_config(**overrides))
    )


async def client_for(app, peer="10.1.1.1"):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=(peer, 12345)),
        base_url="http://testserver",
    )


def base_form(**overrides):
    form = {
        "bank_username": "user1",
        "bank_password": "secret-pin-1234",
        "bank_code": "60050101",
        "bank_url": "https://bank.example/fints30",
        "bank_2fa": "pushTAN",
        "bank_2fa_device": "",
        "firefly_url": "http://firefly:8080",
        "firefly_access_token": "tok-abc",
        "skip_transaction_review": "true",
        "bank_account_iban": "DE00600501010000000000",
        "firefly_account_id": "3",
        "from": "now - 7 days",
        "to": "now",
        "description_regex_match": "",
        "description_regex_replace": "",
    }
    form.update(overrides)
    return form


# --- create ------------------------------------------------------------------

async def test_create_config_writes_file(tmp_path):
    app = build_app(tmp_path)
    async with app.router.lifespan_context(app):
        async with await client_for(app) as c:
            r = await c.post("/configs", data=base_form(filename="neu.json"),
                             follow_redirects=False)
    assert r.status_code == 303
    on_disk = json.loads((tmp_path / "configs" / "neu.json").read_text("utf-8"))
    assert on_disk["bank_password"] == "secret-pin-1234"
    assert on_disk["skip_transaction_review"] == "true"


async def test_create_rejects_bad_filename(tmp_path):
    app = build_app(tmp_path)
    async with app.router.lifespan_context(app):
        async with await client_for(app) as c:
            r = await c.post("/configs", data=base_form(filename="has space.json"))
    assert r.status_code == 200
    assert "Leerzeichen" in r.text  # re-rendered form with error
    assert not (tmp_path / "configs" / "has space.json").exists()


async def test_create_rejects_window_over_90_days(tmp_path):
    app = build_app(tmp_path)
    async with app.router.lifespan_context(app):
        async with await client_for(app) as c:
            r = await c.post("/configs",
                             data=base_form(filename="x.json", **{"from": "now - 120 days"}))
    assert r.status_code == 200
    assert "90" in r.text


# --- edit: secret preservation ----------------------------------------------

async def test_edit_with_empty_password_keeps_existing(tmp_path):
    seed(tmp_path, name="giro.json")
    app = build_app(tmp_path)
    form = base_form()
    form["bank_password"] = ""            # left blank => keep
    form["firefly_access_token"] = ""      # left blank => keep
    form["bank_username"] = "changed-user"  # a visible change
    async with app.router.lifespan_context(app):
        async with await client_for(app) as c:
            r = await c.post("/configs/giro.json", data=form, follow_redirects=False)
    assert r.status_code == 303
    on_disk = json.loads((tmp_path / "configs" / "giro.json").read_text("utf-8"))
    assert on_disk["bank_password"] == "secret-pin-1234"   # preserved
    assert on_disk["firefly_access_token"] == "tok-abc"    # preserved
    assert on_disk["bank_username"] == "changed-user"       # updated


async def test_edit_with_new_password_replaces(tmp_path):
    seed(tmp_path, name="giro.json")
    app = build_app(tmp_path)
    form = base_form(bank_password="brand-new-pin-9999")
    form["firefly_access_token"] = ""
    async with app.router.lifespan_context(app):
        async with await client_for(app) as c:
            await c.post("/configs/giro.json", data=form)
    on_disk = json.loads((tmp_path / "configs" / "giro.json").read_text("utf-8"))
    assert on_disk["bank_password"] == "brand-new-pin-9999"


async def test_edit_form_never_renders_secret(tmp_path):
    seed(tmp_path, name="giro.json")
    app = build_app(tmp_path)
    async with app.router.lifespan_context(app):
        async with await client_for(app) as c:
            r = await c.get("/configs/giro.json/edit")
    assert r.status_code == 200
    assert "secret-pin-1234" not in r.text
    assert "tok-abc" not in r.text


# --- regex audit -------------------------------------------------------------

async def test_regex_change_is_audited(tmp_path):
    seed(tmp_path, name="giro.json")
    app = build_app(tmp_path)
    form = base_form(bank_password="", firefly_access_token="",
                     description_regex_match="/foo/", description_regex_replace="bar")
    async with app.router.lifespan_context(app):
        async with await client_for(app) as c:
            await c.post("/configs/giro.json", data=form)
        audit = app.state.ctx.conn.execute(
            "SELECT action FROM audit WHERE action = 'config.regex_change'"
        ).fetchall()
    assert len(audit) == 1


# --- persistence quick form --------------------------------------------------

async def test_persistence_form_updates_only_that_field(tmp_path):
    seed(tmp_path, name="giro.json")
    app = build_app(tmp_path)
    before = json.loads((tmp_path / "configs" / "giro.json").read_text("utf-8"))
    async with app.router.lifespan_context(app):
        async with await client_for(app) as c:
            r = await c.post("/configs/giro.json/persistence",
                             data={"bank_fints_persistence": "NEW-PERSIST-BLOB=="},
                             follow_redirects=False)
    assert r.status_code == 303
    after = json.loads((tmp_path / "configs" / "giro.json").read_text("utf-8"))
    assert after["bank_fints_persistence"] == "NEW-PERSIST-BLOB=="
    before.pop("bank_fints_persistence")
    after.pop("bank_fints_persistence")
    assert before == after  # nothing else touched


# --- duplicate / delete ------------------------------------------------------

async def test_duplicate_config(tmp_path):
    seed(tmp_path, name="giro.json")
    app = build_app(tmp_path)
    async with app.router.lifespan_context(app):
        async with await client_for(app) as c:
            r = await c.post("/configs/giro.json/duplicate", data={"dest": "kopie.json"},
                             follow_redirects=False)
    assert r.status_code == 303
    assert (tmp_path / "configs" / "kopie.json").exists()


async def test_delete_config_removes_file_and_schedule(tmp_path):
    seed(tmp_path, name="giro.json")
    app = build_app(tmp_path)
    from app import schedules

    async with app.router.lifespan_context(app):
        schedules.upsert(app.state.ctx.conn, "giro.json", enabled=True, cron="0 1 * * *")
        async with await client_for(app) as c:
            r = await c.post("/configs/giro.json/delete", follow_redirects=False)
        assert r.status_code == 303
        assert not (tmp_path / "configs" / "giro.json").exists()
        assert schedules.get(app.state.ctx.conn, "giro.json") is None
