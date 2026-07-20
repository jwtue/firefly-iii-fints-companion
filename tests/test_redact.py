"""Redaction tests. The sentinel test is non-negotiable: seeded secrets must not
survive into any persisted or rendered surface."""

from __future__ import annotations

import logging

from app.redact import (
    MASK,
    RedactingFilter,
    Redactor,
    get_active_redactor,
    redact,
    set_active_redactor,
)

PIN = "PIN-SENTINEL-1234"
TOKEN = "eyJ0okenSENTINELabcdefghijklmnopqrstuvwxyz0123456789ABCDEF"
PERSISTENCE = "cGVyc2lzdGVuY2VTRU5USU5FTGFiY2RlZmdoaWprbG1ub3BxcnN0dXZ3eHl6MDEyMw=="


def test_literal_secret_is_masked():
    r = Redactor([PIN, TOKEN, PERSISTENCE])
    text = f"login failed for pin {PIN} using token {TOKEN}"
    out = r(text)
    assert PIN not in out
    assert TOKEN not in out
    assert MASK in out


def test_short_values_not_redacted():
    """A 3-char value must not turn ordinary text into a wall of masks."""
    r = Redactor(["abc"])
    assert r("the abc of it") == "the abc of it"


def test_longer_secret_matched_before_shorter_substring():
    secret_short = "SENTINELpwd"
    secret_long = "SENTINELpwd-extended-longer-value"
    r = Redactor([secret_short, secret_long])
    out = r(f"value is {secret_long}")
    assert secret_long not in out
    assert "extended-longer-value" not in out  # not left dangling


def test_static_patterns_catch_credential_shapes():
    r = Redactor()  # no literals, only static patterns
    assert "Bearer abc.def.ghi" not in r("Authorization: Bearer abc.def.ghi")
    assert r("PIN: 987654").count(MASK) >= 1
    long_b64 = "A" * 50
    assert long_b64 not in r(f"blob={long_b64}")


def test_none_passthrough():
    assert Redactor([PIN])(None) is None


def test_process_wide_redactor_swap():
    original = get_active_redactor()
    try:
        set_active_redactor(Redactor([PIN]))
        assert PIN not in redact(f"leak {PIN}")
    finally:
        set_active_redactor(original)


def test_logging_filter_scrubs_message(caplog):
    original = get_active_redactor()
    try:
        set_active_redactor(Redactor([PIN]))
        logger = logging.getLogger("test.redact")
        logger.addFilter(RedactingFilter())
        with caplog.at_level(logging.INFO, logger="test.redact"):
            logger.info("boom with %s inside", PIN)
        assert all(PIN not in rec.getMessage() for rec in caplog.records)
    finally:
        set_active_redactor(original)


def test_sentinel_never_survives_full_body():
    """Simulate the display_errors=1 stacktrace-with-credentials case."""
    r = Redactor([PIN, TOKEN, PERSISTENCE])
    body = (
        "<b>Fatal error</b>: Uncaught Exception: auth failed\n"
        f"  bank_password={PIN}\n"
        f"  Authorization: Bearer {TOKEN}\n"
        f"  persistence: {PERSISTENCE}\n"
    )
    out = r(body)
    for secret in (PIN, TOKEN, PERSISTENCE):
        assert secret not in out
