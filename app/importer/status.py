"""Run status vocabulary and the outcome an importer run resolves to.

The single most important design rule of this whole project lives in the detector
(``detect.py``): an unrecognized importer response is a *failure*, never a success.
The old cron predecessor grepped the body only for ``Fatal error`` and therefore
reported ``OK`` for ten days of runs that never happened. Every status here that is
not ``OK``/``OK_NO_TRANSACTIONS`` counts as a failure via :pyattr:`RunStatus.is_failure`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

Detection = Literal["json", "http_status", "heuristic"]


class RunStatus(StrEnum):
    """Terminal classification of a single importer run.

    Ordered loosely from "went fine" to "went wrong". Only the first two are
    successes; everything else is a failure and should surface in the UI and,
    later, in notifications.
    """

    # Successes
    OK = "ok"
    OK_NO_TRANSACTIONS = "ok_no_transactions"

    # The importer stopped at an interactive step (HTTP 200, no error string —
    # exactly the silent-fail class that makes body-grep unreliable).
    TAN_REQUIRED = "tan_required"
    TAN_DEVICE_AMBIGUOUS = "tan_device_ambiguous"

    # The importer rendered error.twig.
    CONFIG_NOT_FOUND = "config_not_found"
    VERIFICATION_FAILED = "verification_failed"

    # A PHP fatal error / uncaught exception leaked into the body.
    IMPORTER_ERROR = "importer_error"

    # Run ended on an unrecognized page — the catch-all failure. This is the
    # default the detector falls back to and the reason the predecessor's silent
    # failures cannot recur here.
    STALLED = "stalled"

    # Transport-level problems the sidecar itself observed.
    TIMEOUT = "timeout"
    UNREACHABLE = "unreachable"

    # The sidecar crashed while handling the run.
    INTERNAL_ERROR = "internal_error"

    @property
    def is_success(self) -> bool:
        return self in (RunStatus.OK, RunStatus.OK_NO_TRANSACTIONS)

    @property
    def is_failure(self) -> bool:
        return not self.is_success

    @property
    def needs_tan(self) -> bool:
        """These call for a human: the user must re-authorise via the importer UI."""
        return self in (RunStatus.TAN_REQUIRED, RunStatus.TAN_DEVICE_AMBIGUOUS)


@dataclass(frozen=True, slots=True)
class RunOutcome:
    """What a detector concluded about one importer response.

    ``error_header`` / ``error_message`` are raw importer text and MUST be passed
    through the redactor before they are persisted or shown — the importer runs
    with ``display_errors=1`` and can leak credentials into these fields.
    """

    status: RunStatus
    detection: Detection
    transactions_sent: int | None = None
    error_header: str | None = None
    error_message: str | None = None
