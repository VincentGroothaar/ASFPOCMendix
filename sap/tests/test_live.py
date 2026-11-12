"""Tests for the live-sandbox helper (sap/tests/live.py, issue #75)."""

import pytest
import requests

from sap.client import SapDataError, SapUnavailable
from sap.tests.live import is_outage, skip_if_sandbox_down
from tests.acceptance.support import read_live_sap


@pytest.mark.parametrize(
    "message",
    [
        "SAP answered with HTTP 500.",
        "SAP answered with HTTP 503.",
        "SAP could not be reached (ConnectionError).",
        "SAP did not answer within 10 s.",
    ],
)
def test_an_outage_skips_the_test(message) -> None:
    assert is_outage(SapUnavailable(message))
    with pytest.raises(pytest.skip.Exception, match="SAP sandbox unavailable"):
        with skip_if_sandbox_down():
            raise SapUnavailable(message)


@pytest.mark.parametrize(
    "error",
    [
        SapUnavailable("SAP answered with HTTP 401."),  # bad key: our configuration
        SapUnavailable("SAP answered with HTTP 400."),  # bad filter: our request
        SapUnavailable("SAP answered with HTTP 404."),  # wrong URL: our request
        SapDataError("SAP answered with something that is not OData JSON."),
        SapDataError("SAP answered with HTTP 500."),  # data errors never count as an outage
    ],
)
def test_anything_that_can_be_our_fault_still_fails(error) -> None:
    assert not is_outage(error)
    with pytest.raises(type(error)):
        with skip_if_sandbox_down():
            raise error


def test_a_failed_assertion_still_fails() -> None:
    with pytest.raises(AssertionError):
        with skip_if_sandbox_down():
            raise AssertionError("wrong shape")


# --- The acceptance tests' own live reads (tests/acceptance/support.py) -----------------------


class _Answer:
    def __init__(self, status: int) -> None:
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


@pytest.mark.parametrize(
    "outcome",
    [_Answer(500), _Answer(503), requests.ConnectionError(), requests.Timeout()],
    ids=["500", "503", "no connection", "timeout"],
)
def test_live_reads_in_acceptance_tests_skip_on_an_outage(monkeypatch, outcome) -> None:
    monkeypatch.setenv("SAP_API_KEY", "test-key")

    def get(*args, **kwargs):
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(requests, "get", get)
    with pytest.raises(pytest.skip.Exception, match="SAP sandbox unavailable"):
        read_live_sap("API_PRODUCT_SRV/A_ProductDescription", {})


def test_live_reads_in_acceptance_tests_fail_on_a_4xx(monkeypatch) -> None:
    monkeypatch.setenv("SAP_API_KEY", "test-key")
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: _Answer(401))

    with pytest.raises(requests.HTTPError):
        read_live_sap("API_PRODUCT_SRV/A_ProductDescription", {})
