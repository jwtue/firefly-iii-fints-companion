"""i18n tests: catalog integrity, language resolution, request rendering, switcher."""

from __future__ import annotations

import httpx
import pytest

from app.i18n import CATALOG, resolve_lang, translate
from app.main import create_app
from app.settings import Settings


# --- catalog -----------------------------------------------------------------

def test_de_and_en_have_identical_keys():
    en = set(CATALOG["en"])
    de = set(CATALOG["de"])
    assert en == de, f"key mismatch: only en={en - de}, only de={de - en}"


def test_translate_falls_back_to_english_then_key():
    # A key present only in en (simulate by using a real key) returns en for de-miss.
    assert translate("de", "nav.overview") == "Übersicht"
    assert translate("en", "nav.overview") == "Overview"
    # Unknown key returns the key itself.
    assert translate("de", "does.not.exist") == "does.not.exist"


def test_translate_formats_kwargs():
    assert "5" in translate("en", "schedule.catchup_days", n=5)
    assert "5" in translate("de", "schedule.catchup_days", n=5)


# --- language resolution -----------------------------------------------------

@pytest.mark.parametrize("cookie,accept,expected", [
    ("de", "en-US,en;q=0.9", "de"),      # cookie wins
    ("en", "de", "en"),                   # cookie wins
    (None, "de-DE,de;q=0.9,en;q=0.5", "de"),
    (None, "en-GB,en;q=0.9,de;q=0.5", "en"),
    (None, "fr-FR,fr;q=0.9", "en"),       # unsupported => default en
    (None, None, "en"),                   # nothing => default en
    ("xx", "de", "de"),                   # invalid cookie ignored, header used
])
def test_resolve_lang(cookie, accept, expected):
    assert resolve_lang(cookie, accept) == expected


# --- request rendering -------------------------------------------------------

def build_app(tmp_path):
    settings = Settings(
        config_dir=tmp_path / "configs",
        state_dir=tmp_path / "state",
        trusted_networks=["10.0.0.0/8"],
    )
    settings.validate_auth()
    return create_app(settings)


async def client_for(app, peer="10.1.1.1", headers=None):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=(peer, 12345)),
        base_url="http://testserver",
        headers=headers or {},
    )


async def test_default_render_is_english(tmp_path):
    app = build_app(tmp_path)
    async with app.router.lifespan_context(app):
        async with await client_for(app) as c:
            r = await c.get("/")
    assert "Overview" in r.text
    assert "Übersicht" not in r.text


async def test_accept_language_de_renders_german(tmp_path):
    app = build_app(tmp_path)
    async with app.router.lifespan_context(app):
        async with await client_for(app, headers={"Accept-Language": "de-DE,de;q=0.9"}) as c:
            r = await c.get("/")
    assert "Übersicht" in r.text
    assert "Overview" not in r.text


async def test_lang_cookie_overrides_header(tmp_path):
    app = build_app(tmp_path)
    async with app.router.lifespan_context(app):
        async with await client_for(app, headers={"Accept-Language": "en"}) as c:
            c.cookies.set("lang", "de")
            r = await c.get("/")
    assert "Übersicht" in r.text


async def test_switcher_sets_cookie_and_redirects(tmp_path):
    app = build_app(tmp_path)
    async with app.router.lifespan_context(app):
        async with await client_for(app) as c:
            r = await c.get("/lang/de?next=/schedules", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/schedules"
    assert "lang=de" in r.headers.get("set-cookie", "")


async def test_switcher_rejects_external_redirect(tmp_path):
    app = build_app(tmp_path)
    async with app.router.lifespan_context(app):
        async with await client_for(app) as c:
            r = await c.get("/lang/de?next=https://evil.example", follow_redirects=False)
    assert r.headers["location"] == "/"  # falls back to same-site root


async def test_switcher_is_public_prelogin(tmp_path):
    """With password auth, /lang must work without a session (for the login page)."""
    from app.auth import hash_password

    settings = Settings(
        config_dir=tmp_path / "configs",
        state_dir=tmp_path / "state",
        password_hash=hash_password("pw"),
        secret_key="0123456789abcdef0123",
    )
    settings.validate_auth()
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        # Untrusted peer, no session — normally redirected to /login, but /lang is public.
        async with await client_for(app, peer="203.0.113.9") as c:
            r = await c.get("/lang/de?next=/login", follow_redirects=False)
    assert r.status_code == 303
    assert "lang=de" in r.headers.get("set-cookie", "")
