"""Notification backend contract and the message model.

Hand-rolled rather than pulling in apprise: the app's #1 security property is that
secrets never leave the process, so every outbound body passes through the one
redactor chokepoint (applied by the dispatcher before a backend ever sees the text).
The URL syntax mirrors apprise (tgram://, ntfy://, ...) so swapping to the library
later is a one-file change here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Message:
    title: str
    body: str
    # Higher = more urgent. Backends that support priorities map this on.
    priority: int = 0


class NotifyBackend(Protocol):
    #: URL scheme this backend handles, e.g. "ntfy".
    scheme: str

    async def send(self, message: Message) -> None:
        """Deliver the message. Raise on failure; the dispatcher records it."""
        ...
