"""HTTP client that triggers an importer run.

Just enough to fire the automate URL and hand the response to the detector chain.
Transport failures (timeout, connection refused) are turned into typed results so
the runner can classify them without catching httpx exceptions itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

import httpx

from .status import RunStatus


@dataclass(frozen=True, slots=True)
class TriggerResult:
    """Outcome of the HTTP call itself, before body classification."""

    response: httpx.Response | None
    transport_status: RunStatus | None  # set iff the call never produced a response
    transport_error: str | None = None


class ImporterClient:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float,
        *,
        supports_json: bool = False,
        transport: httpx.BaseTransport | httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout_seconds
        self.supports_json = supports_json
        # Tests inject an ASGITransport to drive the stub importer in-process.
        self._transport = transport

    def build_url(self, config_name: str) -> str:
        # config_name is validated upstream (no spaces/traversal); still quote it
        # defensively. format=json is appended only once upstream supports it.
        params = f"automate=true&config={quote(config_name)}"
        if self.supports_json:
            params += "&format=json"
        return f"{self.base_url}/?{params}"

    async def trigger(self, config_name: str) -> TriggerResult:
        url = self.build_url(config_name)
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=False,
                transport=self._transport,
            ) as client:
                resp = await client.get(url)
            return TriggerResult(response=resp, transport_status=None)
        except httpx.TimeoutException as exc:
            return TriggerResult(None, RunStatus.TIMEOUT, f"importer timed out: {exc!r}")
        except httpx.HTTPError as exc:
            return TriggerResult(None, RunStatus.UNREACHABLE, f"importer unreachable: {exc!r}")
