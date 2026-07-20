"""Parse notify URLs into backends. Swap point if apprise is adopted later."""

from __future__ import annotations

import logging
from urllib.parse import urlsplit

from .base import NotifyBackend
from .ntfy import NtfyBackend
from .telegram import TelegramBackend

logger = logging.getLogger("sidecar.notify")

# scheme → backend factory. ntfys shares the ntfy backend (TLS handled inside).
_FACTORIES = {
    "ntfy": NtfyBackend,
    "ntfys": NtfyBackend,
    "tgram": TelegramBackend,
    "tgrams": TelegramBackend,
}

SUPPORTED_SCHEMES = tuple(sorted(_FACTORIES))


def build_backends(urls: list[str]) -> list[NotifyBackend]:
    backends: list[NotifyBackend] = []
    for url in urls:
        scheme = urlsplit(url).scheme
        factory = _FACTORIES.get(scheme)
        if factory is None:
            logger.error("unsupported notify scheme %r (supported: %s)",
                         scheme, ", ".join(SUPPORTED_SCHEMES))
            continue
        try:
            backends.append(factory(url))
        except Exception as exc:  # noqa: BLE001 — a bad URL must not break startup
            logger.error("could not build notify backend for scheme %r: %s", scheme, exc)
    return backends
