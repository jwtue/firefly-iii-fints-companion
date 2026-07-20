"""End-to-end tests over the full ASGI app: auth gating, dashboard, run flow."""

from __future__ import annotations

import httpx
import pytest

from app.importer.client import ImporterClient
from app.main import create_app
from app.models import FintsConfig
from app.settings import Settings

from .stub.importer import app as stub_app
from .test_models import base_config


def build_app(tmp_path, **settings_overrides):
    settings = Settings(
        config_dir=tmp_path / "configs",
        state_dir=tmp_path / "state",
        **settings_overrides,
    )
    settings.validate_auth()
    app = create_app(settings)
    # Point the importer client at the in-process stub.
    ctx = app.state.ctx
    ctx.client = ImporterClient(
        "http://stub", timeout_seconds=5.0, transport=httpx.ASGITransport(app=stub_app)
    )
    return app


def seed_config(tmp_path, name="ok.json", **overrides):
    from app.configstore import ConfigStore

    store = ConfigStore(tmp_path / "configs")
    store.write(name, FintsConfig.model_validate(base_config(**overrides)))


async def client_for(app, peer="10.9.9.9"):
    transport = httpx.ASGITransport(app=app, client=(peer, 12345))
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


# --- fail-closed settings ----------------------------------------------------

def test_settings_refuse_wide_open(tmp_path):
    s = Settings(config_dir=tmp_path, state_dir=tmp_path, password_hash="", trusted_networks=[])
    with pytest.raises(RuntimeError, match="Refusing to start"):
        s.validate_auth()


def test_settings_password_requires_secret_key(tmp_path):
    s = Settings(config_dir=tmp_path, state_dir=tmp_path, password_hash="x", secret_key="")
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        s.validate_auth()


# --- auth gating -------------------------------------------------------------

async def test_healthz_is_public(tmp_path):
    app = build_app(tmp_path, trusted_networks=["127.0.0.1/32"])
    async with app.router.lifespan_context(app):
        async with await client_for(app, peer="203.0.113.5") as c:
            r = await c.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


async def test_untrusted_peer_redirected_to_login(tmp_path):
    app = build_app(tmp_path, trusted_networks=["192.168.0.0/16"])
    async with app.router.lifespan_context(app):
        async with await client_for(app, peer="203.0.113.5") as c:
            r = await c.get("/", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/login"


async def test_trusted_peer_bypasses_auth(tmp_path):
    seed_config(tmp_path)
    app = build_app(tmp_path, trusted_networks=["10.0.0.0/8"])
    async with app.router.lifespan_context(app):
        async with await client_for(app, peer="10.9.9.9") as c:
            r = await c.get("/")
    assert r.status_code == 200
    assert "Overview" in r.text  # default language is English


async def test_spoofed_forwarded_for_does_not_bypass(tmp_path):
    """An untrusted peer sending X-Forwarded-For of a trusted IP must NOT bypass."""
    app = build_app(tmp_path, trusted_networks=["10.0.0.0/8"])
    async with app.router.lifespan_context(app):
        async with await client_for(app, peer="203.0.113.5") as c:
            r = await c.get("/", headers={"X-Forwarded-For": "10.0.0.1"}, follow_redirects=False)
    assert r.status_code == 302  # still redirected to login


# --- run flow (the M1 payoff) ------------------------------------------------

async def test_manual_run_records_and_shows_result(tmp_path):
    seed_config(tmp_path, name="ok.json")
    app = build_app(tmp_path, trusted_networks=["10.0.0.0/8"])
    async with app.router.lifespan_context(app):
        async with await client_for(app, peer="10.1.1.1") as c:
            r = await c.post("/configs/ok.json/run", follow_redirects=False)
            assert r.status_code == 303
            detail = await c.get(r.headers["location"])
    assert detail.status_code == 200
    assert "OK" in detail.text
    assert "12" in detail.text  # transactions


async def test_manual_run_of_broken_config_is_visible_failure(tmp_path):
    """A config the importer can't find must surface as a failure, not silent OK."""
    seed_config(tmp_path, name="ok.json")
    app = build_app(tmp_path, trusted_networks=["10.0.0.0/8"])
    async with app.router.lifespan_context(app):
        async with await client_for(app, peer="10.1.1.1") as c:
            # 'missing.json' maps to config_not_found in the stub, but it must
            # exist on disk to be runnable — seed it too.
            seed_config(tmp_path, name="missing.json")
            r = await c.post("/configs/missing.json/run", follow_redirects=False)
            detail = await c.get(r.headers["location"])
    assert "config not found" in detail.text  # translated status badge (default en)
