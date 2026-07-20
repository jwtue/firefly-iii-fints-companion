"""Redaction — keep secrets from ever leaving the process.

The configs this sidecar manages hold the bank PIN, the FinTS persistence string
and the Firefly access token in cleartext. The importer runs with
``display_errors=1``, so a fatal error can splice those very values into an HTML
stacktrace that we then store and render. Redaction is therefore not a nicety; it
is the app's primary security property.

Three mandatory chokepoints route through here (see the plan):
  1. a :class:`logging.Filter` on the root logger,
  2. the importer ``response_body`` in ``runner.py`` *before* the DB insert,
  3. any error text persisted or rendered.

The :class:`Redactor` is rebuilt from all current configs on every config write so
newly-added secrets are covered immediately.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable

MASK = "███REDACTED███"

# Minimum length for a config-derived value to be treated as a secret. Below this
# a value (e.g. a 3-char username) is too short to redact without shredding
# ordinary text; such values should not be secrets anyway.
_MIN_SECRET_LEN = 5

# Static patterns that catch credential shapes regardless of the config set.
_STATIC_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]+"),
    re.compile(r"(?i)\bPIN\b\s*[=:]\s*\S+"),
    re.compile(r"(?i)\bpass(?:word|wort)?\b\s*[=:]\s*\S+"),
    # Long base64-ish runs — the FinTS persistence blob and access tokens look
    # like this. 40+ chars avoids eating ordinary words.
    re.compile(r"[A-Za-z0-9+/]{40,}={0,2}"),
)


class Redactor:
    """Callable that masks known secret values and credential-shaped substrings.

    Build it with the concrete secret strings (bank password, token, persistence
    string, ...). Longer values are matched first so a token that contains a
    shorter secret as a substring still redacts cleanly.
    """

    def __init__(self, secrets: Iterable[str] = ()) -> None:
        values = sorted(
            {s for s in secrets if s and len(s) >= _MIN_SECRET_LEN},
            key=len,
            reverse=True,
        )
        self._literal = (
            re.compile("|".join(re.escape(v) for v in values)) if values else None
        )

    def __call__(self, text: str | None) -> str | None:
        if text is None:
            return None
        if self._literal is not None:
            text = self._literal.sub(MASK, text)
        for pattern in _STATIC_PATTERNS:
            text = pattern.sub(MASK, text)
        return text

    def redact(self, text: str | None) -> str | None:
        return self(text)


# A process-wide redactor. It starts with only the static patterns and is replaced
# via :func:`set_active_redactor` whenever configs are (re)loaded, so the logging
# filter and any ad-hoc callers always see the current secret set.
_active = Redactor()


def set_active_redactor(redactor: Redactor) -> None:
    global _active
    _active = redactor


def get_active_redactor() -> Redactor:
    return _active


def redact(text: str | None) -> str | None:
    """Redact using the process-wide active redactor."""
    return _active(text)


class RedactingFilter(logging.Filter):
    """Root-logger filter that scrubs formatted log records.

    Catches stacktraces and third-party log lines that would otherwise leak
    credentials. Applied to the record's rendered message and args.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if record.args:
                record.msg = _active(record.getMessage()) or ""
                record.args = ()
            elif isinstance(record.msg, str):
                record.msg = _active(record.msg) or ""
        except Exception:  # noqa: BLE001 — logging must never raise
            record.msg = "[redaction error: message suppressed]"
            record.args = ()
        return True


def install_logging_filter() -> None:
    """Attach the redacting filter to the root logger and its handlers."""
    root = logging.getLogger()
    filt = RedactingFilter()
    root.addFilter(filt)
    for handler in root.handlers:
        handler.addFilter(filt)
