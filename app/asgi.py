"""ASGI entrypoint for uvicorn: ``uvicorn app.asgi:app``.

Building the app calls ``settings.validate_auth()``, which raises on an unsafe
configuration — so a misconfigured container fails to start rather than coming up
wide open.
"""

from __future__ import annotations

from .main import create_app

app = create_app()
