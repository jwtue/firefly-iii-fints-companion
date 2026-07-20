"""Telegram backend. URL: tgram://bottoken/chatid (apprise-compatible)."""

from __future__ import annotations

from urllib.parse import urlsplit

import httpx

from .base import Message


class TelegramBackend:
    scheme = "tgram"

    def __init__(self, url: str):
        parts = urlsplit(url)
        # apprise packs the bot token in the host and the chat id in the path.
        self._token = parts.netloc
        self._chat_id = parts.path.strip("/")
        if not self._token or not self._chat_id:
            raise ValueError("telegram URL must be tgram://bottoken/chatid")

    async def send(self, message: Message) -> None:
        text = f"{message.title}\n\n{message.body}" if message.title else message.body
        endpoint = f"https://api.telegram.org/bot{self._token}/sendMessage"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                endpoint,
                json={"chat_id": self._chat_id, "text": text, "disable_web_page_preview": True},
            )
            resp.raise_for_status()
