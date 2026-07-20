"""A fake importer for tests and the docker-compose smoke test.

Maps ``?config=<name>`` to a recorded HTML fixture and, like the real importer,
answers everything with HTTP 200 and HTML unless a fixture is configured to do
otherwise. Deliberately tiny.

Query params:
  config=<name>   pick the fixture mapped to this config name (default: setup_list)
  delay=<sec>     sleep before responding (to exercise timeouts)
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import FastAPI, Request, Response

FIXTURES = Path(__file__).parent.parent / "fixtures" / "importer"

# config name → fixture file. Unmapped names fall through to the silent stall,
# exactly like requesting a config the importer can't find in automate mode.
CONFIG_TO_FIXTURE = {
    "ok.json": "done_12tx.html",
    "empty-import.json": "done_0tx.html",
    "missing.json": "error_config_not_found.html",
    "badaccount.json": "error_verify_failed.html",
    "tan.json": "tan_challenge.html",
    "device.json": "choose_2fa_device.html",
    "fatal.json": "php_fatal.html",
}

app = FastAPI()


@app.get("/")
async def automate(request: Request) -> Response:
    config = request.query_params.get("config", "")
    delay = float(request.query_params.get("delay", "0") or "0")
    if delay:
        await asyncio.sleep(delay)
    fixture = CONFIG_TO_FIXTURE.get(config, "setup_list.html")
    body = (FIXTURES / fixture).read_text(encoding="utf-8")
    # The real importer always returns 200 + HTML in automate mode.
    return Response(content=body, media_type="text/html; charset=UTF-8", status_code=200)
