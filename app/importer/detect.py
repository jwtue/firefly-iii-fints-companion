"""Classify an importer HTTP response into a :class:`RunOutcome`.

The importer answers *everything* — success, missing config, TAN required, PHP
fatal error — with HTTP 200 and HTML. There is no machine-readable status (verified
against upstream master, last commit 2026-05-23). So detection is a chain of
adapters, first match wins:

    JsonStatusDetector   — active once the upstream status PR lands (Content-Type JSON)
    HttpStatusDetector   — active once responses carry a real status code (!= 200)
    HtmlHeuristicDetector — terminal fallback, always matches, parses the HTML

The first two are inert against today's importer (always 200, always HTML) yet cost
nothing to keep in place: when the PR merges, the sidecar starts trusting the status
without a rewrite.

CENTRAL RULE: the heuristic's default branch is FAILURE (``STALLED``), never success.
A run that ends on ``setup.twig`` / ``choose-2fa-device.twig`` / an empty body is a
run that did not import. That default is why the predecessor's silent failures cannot
recur — test it first, guard it forever.
"""

from __future__ import annotations

import re
from typing import Protocol, runtime_checkable

import httpx

from .status import RunOutcome, RunStatus


@runtime_checkable
class StatusDetector(Protocol):
    def supports(self, resp: httpx.Response) -> bool: ...
    def detect(self, resp: httpx.Response) -> RunOutcome: ...


# --- JSON detector -----------------------------------------------------------

# Maps the ``status`` field of the upstream JSON payload (see the M0 PR) onto our
# vocabulary. Any status string the payload might carry that we don't know about
# still resolves to a failure via the ``.get(..., STALLED)`` default below.
_JSON_STATUS_MAP: dict[str, RunStatus] = {
    "ok": RunStatus.OK,
    "tan_required": RunStatus.TAN_REQUIRED,
    "tan_device_ambiguous": RunStatus.TAN_DEVICE_AMBIGUOUS,
    "config_not_found": RunStatus.CONFIG_NOT_FOUND,
    "verification_failed": RunStatus.VERIFICATION_FAILED,
    "importer_error": RunStatus.IMPORTER_ERROR,
    "stalled": RunStatus.STALLED,
}


class JsonStatusDetector:
    """Trusts a JSON body from the (future) ``&format=json`` automate mode."""

    def supports(self, resp: httpx.Response) -> bool:
        return "application/json" in resp.headers.get("content-type", "").lower()

    def detect(self, resp: httpx.Response) -> RunOutcome:
        try:
            payload = resp.json()
        except (ValueError, TypeError):
            return RunOutcome(
                RunStatus.STALLED,
                "json",
                error_header="Importer returned a JSON content-type with an unparseable body",
            )
        raw = str(payload.get("status", "")).strip().lower()
        status = _JSON_STATUS_MAP.get(raw, RunStatus.STALLED)
        tx = payload.get("transactions")
        if status is RunStatus.OK and isinstance(tx, int) and tx == 0:
            status = RunStatus.OK_NO_TRANSACTIONS
        return RunOutcome(
            status,
            "json",
            transactions_sent=tx if isinstance(tx, int) else None,
            error_header=payload.get("error_header") or None,
            error_message=payload.get("error_message") or None,
        )


# --- HTTP status detector ----------------------------------------------------

# Maps HTTP status codes from the (future) patched importer. Only fires on non-200;
# every mapped and unmapped non-200 is a failure, so a stray proxy 502 today is
# safely classified rather than mistaken for success.
_HTTP_STATUS_MAP: dict[int, RunStatus] = {
    404: RunStatus.CONFIG_NOT_FOUND,
    409: RunStatus.TAN_REQUIRED,
}


class HttpStatusDetector:
    """Trusts a real HTTP status code once the importer sets one (!= 200)."""

    def supports(self, resp: httpx.Response) -> bool:
        return resp.status_code != 200

    def detect(self, resp: httpx.Response) -> RunOutcome:
        status = _HTTP_STATUS_MAP.get(resp.status_code, RunStatus.IMPORTER_ERROR)
        return RunOutcome(status, "http_status")


# --- HTML heuristic detector -------------------------------------------------

_H1_RE = re.compile(r"<h1[^>]*>\s*(.*?)\s*</h1>", re.IGNORECASE | re.DOTALL)


def _extract_h1(body: str) -> str | None:
    m = _H1_RE.search(body)
    if not m:
        return None
    # Strip any nested tags and collapse whitespace.
    text = re.sub(r"<[^>]+>", "", m.group(1))
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


class HtmlHeuristicDetector:
    """Terminal fallback: parse the HTML body. Always ``supports``.

    Failure rules are checked BEFORE the success marker on purpose: if a partial
    import is followed by a fatal error, the fatal error must win.
    """

    _SUCCESS = re.compile(r"(\d+)\s+transactions have been sent to Firefly III")

    # (pattern, status) — evaluated in order, first hit wins.
    _RULES: list[tuple[re.Pattern[str], RunStatus]] = [
        (re.compile(r"Fatal error|Uncaught\s+\w*(?:Exception|Error)", re.IGNORECASE),
         RunStatus.IMPORTER_ERROR),
        (re.compile(r"Could not find the configuration", re.IGNORECASE),
         RunStatus.CONFIG_NOT_FOUND),
        (re.compile(r"Failed to verify given Information", re.IGNORECASE),
         RunStatus.VERIFICATION_FAILED),
        (re.compile(r"The bank requested a TAN", re.IGNORECASE),
         RunStatus.TAN_REQUIRED),
        (re.compile(r"choose-2fa-device|name=[\"']tan_device", re.IGNORECASE),
         RunStatus.TAN_DEVICE_AMBIGUOUS),
    ]

    def supports(self, resp: httpx.Response) -> bool:
        return True

    def detect(self, resp: httpx.Response) -> RunOutcome:
        body = resp.text
        for rx, status in self._RULES:
            if rx.search(body):
                return RunOutcome(status, "heuristic", error_header=_extract_h1(body))

        m = self._SUCCESS.search(body)
        if m:
            n = int(m.group(1))
            return RunOutcome(
                RunStatus.OK if n > 0 else RunStatus.OK_NO_TRANSACTIONS,
                "heuristic",
                transactions_sent=n,
            )

        # DEFAULT IS FAILURE. setup.twig, choose-account.twig, an empty body, a
        # redirect page, anything we don't recognise. This single line is the
        # reason the ten-day silent outage cannot repeat. Do not "optimise" it
        # into an OK branch.
        return RunOutcome(
            RunStatus.STALLED,
            "heuristic",
            error_header="Run ended at an unrecognized importer page",
        )


# The default chain. JSON and HTTP detectors are cheap and inert until upstream
# provides real signals; the HTML heuristic is the guaranteed terminal fallback.
DEFAULT_CHAIN: tuple[StatusDetector, ...] = (
    JsonStatusDetector(),
    HttpStatusDetector(),
    HtmlHeuristicDetector(),
)


def detect(resp: httpx.Response, chain: tuple[StatusDetector, ...] = DEFAULT_CHAIN) -> RunOutcome:
    """Run the detector chain and return the first applicable outcome."""
    for detector in chain:
        if detector.supports(resp):
            return detector.detect(resp)
    # Unreachable in practice — HtmlHeuristicDetector always supports — but if a
    # custom chain omits it, fail closed rather than raise.
    return RunOutcome(
        RunStatus.STALLED,
        "heuristic",
        error_header="No detector matched the response",
    )
