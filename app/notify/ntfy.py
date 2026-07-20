"""ntfy backend. URL: ntfy://host/topic or ntfys://host/topic (TLS)."""

from __future__ import annotations

from urllib.parse import urlsplit

import httpx

from .base import Message


class NtfyBackend:
    scheme = "ntfy"

    def __init__(self, url: str):
        parts = urlsplit(url)
        secure = parts.scheme == "ntfys"
        host = parts.netloc
        topic = parts.path.strip("/")
        if not host or not topic:
            raise ValueError("ntfy URL must be ntfy://host/topic")
        proto = "https" if secure else "http"
        self._endpoint = f"{proto}://{host}/{topic}"

    async def send(self, message: Message) -> None:
        # ntfy priority is 1..5 (3 = default). Map our 0..2 upward.
        ntfy_prio = min(5, 3 + max(0, message.priority))
        headers = {
            "Title": message.title.encode("utf-8", "replace").decode("latin-1", "replace"),
            "Priority": str(ntfy_prio),
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(self._endpoint, content=message.body.encode("utf-8"),
                                     headers=headers)
            resp.raise_for_status()
