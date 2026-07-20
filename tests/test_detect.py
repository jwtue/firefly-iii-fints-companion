"""Tests for the status detector chain — the heart of the sidecar.

The property test at the bottom (`test_no_success_marker_never_ok`) encodes the
central rule: no HTML lacking the success marker may ever be classified as a
success. It is the guard against the ten-day silent-outage failure class.
"""

from __future__ import annotations

import pytest

from app.importer.detect import (
    DEFAULT_CHAIN,
    HtmlHeuristicDetector,
    HttpStatusDetector,
    JsonStatusDetector,
    detect,
)
from app.importer.status import RunStatus

from .conftest import load_fixture, make_response

# --- HTML heuristic: exact status per recorded fixture -----------------------

FIXTURE_EXPECTATIONS = [
    ("done_12tx.html", RunStatus.OK, 12),
    ("done_0tx.html", RunStatus.OK_NO_TRANSACTIONS, 0),
    ("error_config_not_found.html", RunStatus.CONFIG_NOT_FOUND, None),
    ("error_verify_failed.html", RunStatus.VERIFICATION_FAILED, None),
    ("tan_challenge.html", RunStatus.TAN_REQUIRED, None),
    ("choose_2fa_device.html", RunStatus.TAN_DEVICE_AMBIGUOUS, None),
    ("setup_list.html", RunStatus.STALLED, None),
    ("php_fatal.html", RunStatus.IMPORTER_ERROR, None),
    ("empty.html", RunStatus.STALLED, None),
]


@pytest.mark.parametrize("filename,expected_status,expected_tx", FIXTURE_EXPECTATIONS)
def test_html_fixture_classification(filename, expected_status, expected_tx):
    resp = make_response(load_fixture(filename))
    outcome = detect(resp)
    assert outcome.status is expected_status, f"{filename} misclassified"
    assert outcome.detection == "heuristic"
    assert outcome.transactions_sent == expected_tx


def test_setup_list_is_the_silent_stall():
    """setup.twig (no config chosen) is HTTP 200 with no error string. The old
    cron would have called this OK. It must be a failure."""
    outcome = detect(make_response(load_fixture("setup_list.html")))
    assert outcome.status.is_failure


def test_fatal_error_after_partial_import_wins():
    """Failure rules run before the success marker: a fatal error after some
    transactions were already sent must classify as importer_error, not OK."""
    body = (
        "<h1>Import</h1><p>5 transactions have been sent to Firefly III.</p>"
        "<br /><b>Fatal error</b>: Uncaught Exception: connection reset"
    )
    outcome = detect(make_response(body))
    assert outcome.status is RunStatus.IMPORTER_ERROR


# --- The property test: the single most important guarantee ------------------

# Every string that does NOT contain the exact success marker. Includes junk,
# partial pages, redirects, and near-miss text.
NON_SUCCESS_BODIES = [
    "",
    "   \n\t ",
    "<html><body>totally unrelated page</body></html>",
    "<h1>Firefly III FinTS Importer</h1><form><select name='config'></select></form>",
    "The bank requested a TAN, asking: enter code",
    "<h1>Could not find the configuration</h1>",
    "0 transactions have been sent to Firefly III.",  # success marker but zero
    "302 Found. Redirecting to /login",
    "<b>Fatal error</b>: boom",
    "transactions have been sent to Firefly III.",  # marker without a number → no match
    "<h1>Some brand new importer page we have never seen</h1>",
    "gateway timeout",
]


@pytest.mark.parametrize("body", NON_SUCCESS_BODIES)
def test_no_success_marker_never_ok(body):
    """CORE INVARIANT: a body without a positive '<n> transactions have been sent'
    marker (n > 0) must never resolve to RunStatus.OK. Unknown pages fall through
    to STALLED, a failure."""
    outcome = detect(make_response(body))
    assert outcome.status is not RunStatus.OK
    # And an unrecognised body specifically becomes STALLED.
    if not HtmlHeuristicDetector._SUCCESS.search(body) and not any(
        rx.search(body) for rx, _ in HtmlHeuristicDetector._RULES
    ):
        assert outcome.status is RunStatus.STALLED


def test_unknown_body_defaults_to_stalled():
    outcome = detect(make_response("<html>surprise</html>"))
    assert outcome.status is RunStatus.STALLED
    assert outcome.status.is_failure


# --- JSON detector (future upstream PR) --------------------------------------

def test_json_detector_success():
    resp = make_response(
        '{"status": "ok", "transactions": 7}',
        content_type="application/json",
    )
    outcome = detect(resp)
    assert outcome.detection == "json"
    assert outcome.status is RunStatus.OK
    assert outcome.transactions_sent == 7


def test_json_detector_zero_transactions():
    resp = make_response(
        '{"status": "ok", "transactions": 0}',
        content_type="application/json",
    )
    assert detect(resp).status is RunStatus.OK_NO_TRANSACTIONS


def test_json_detector_tan_required():
    resp = make_response(
        '{"status": "tan_required", "error_header": "TAN required"}',
        content_type="application/json",
    )
    assert detect(resp).status is RunStatus.TAN_REQUIRED


def test_json_detector_unknown_status_is_failure():
    resp = make_response('{"status": "who_knows"}', content_type="application/json")
    assert detect(resp).status is RunStatus.STALLED


def test_json_detector_broken_body_is_failure():
    resp = make_response("not json at all", content_type="application/json")
    assert detect(resp).status is RunStatus.STALLED


# --- HTTP status detector (future upstream PR) -------------------------------

def test_http_status_detector_maps_known_codes():
    assert detect(make_response("x", status_code=404)).status is RunStatus.CONFIG_NOT_FOUND
    assert detect(make_response("x", status_code=409)).status is RunStatus.TAN_REQUIRED


def test_http_status_detector_unknown_non_200_is_failure():
    outcome = detect(make_response("Bad Gateway", status_code=502))
    assert outcome.detection == "http_status"
    assert outcome.status.is_failure


def test_http_status_does_not_fire_on_200():
    """Against today's importer (always 200) the HTTP detector must stay inert so
    the HTML heuristic gets to classify the body."""
    d = HttpStatusDetector()
    assert d.supports(make_response("x", status_code=200)) is False


def test_chain_order_json_beats_html():
    """A JSON success body must be read as JSON even though it isn't HTML."""
    resp = make_response('{"status":"ok","transactions":3}', content_type="application/json")
    assert detect(resp).detection == "json"


def test_html_detector_always_supports():
    assert HtmlHeuristicDetector().supports(make_response("anything")) is True
    assert JsonStatusDetector().supports(make_response("<html/>")) is False


def test_default_chain_is_terminal():
    """The default chain must always yield an outcome for any response."""
    for body in ("", "<html/>", "junk"):
        assert detect(make_response(body)) is not None
    assert len(DEFAULT_CHAIN) == 3
