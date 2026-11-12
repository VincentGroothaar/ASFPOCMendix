"""Tests for the requisition write client (#27, R-4). No network: a fake session answers."""

import json
from datetime import date
from decimal import Decimal

import pytest
import requests

from sap.requisitions import (
    NOT_ACCEPTED,
    TIMEOUT_SECONDS,
    UNREACHABLE,
    build_payload,
    create_requisition,
)

BASE = "https://mock.test"
KEY = "secret-mock-key"
SERVICE = f"{BASE}/sap/opu/odata/sap/API_PURCHASEREQ_PROCESS_SRV"


def answer(status: int, body=None, headers: dict | None = None, text: str | None = None):
    """A requests.Response as the mock would send it."""
    response = requests.Response()
    response.status_code = status
    response.headers.update(headers or {})
    if text is not None:
        response._content = text.encode()
    elif body is not None:
        response._content = json.dumps(body).encode()
    else:
        response._content = b""
    return response


def odata_error(message: str) -> dict:
    return {"error": {"code": "INVALID_REQUISITION", "message": {"lang": "en", "value": message}}}


class FakeSession:
    """Records calls and plays back the token answer and the POST answer."""

    def __init__(self, token_answer=None, post_answer=None, raise_on=None) -> None:
        self.headers: dict[str, str] = {}
        self.calls: list[tuple[str, str, dict, object]] = []
        # `is None`, not `or`: a requests.Response with a 4xx or 5xx status is falsy.
        if token_answer is None:
            token_answer = answer(200, {"d": {}}, {"X-CSRF-Token": "tok-1"})
        if post_answer is None:
            post_answer = answer(201, {"d": {"PurchaseRequisition": "10000000"}})
        self.token_answer = token_answer
        self.post_answer = post_answer
        self.raise_on = raise_on or {}

    def get(self, url, headers=None, timeout=None):
        self.calls.append(("GET", url, {**self.headers, **(headers or {})}, timeout))
        if "GET" in self.raise_on:
            raise self.raise_on["GET"]
        return self.token_answer

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append(("POST", url, {**self.headers, **(headers or {})}, json))
        if "POST" in self.raise_on:
            raise self.raise_on["POST"]
        return self.post_answer


PAYLOAD = build_payload("RM-1", "AUC1", Decimal("500.000"), "G", date(2026, 11, 20))


def send(session: FakeSession):
    return create_requisition(PAYLOAD, base_url=BASE, api_key=KEY, session=session)


# --- Payload ------------------------------------------------------------------------------------


def test_payload_is_one_header_with_one_item_in_sap_field_names():
    assert PAYLOAD == {
        "PurchaseRequisitionType": "NB",
        "to_PurchaseReqnItem": [
            {
                "Material": "RM-1",
                "Plant": "AUC1",
                "RequestedQuantity": "500.000",
                "BaseUnit": "G",
                "DeliveryDate": "/Date(1795132800000)/",
                "PurchasingGroup": "001",
            }
        ],
    }


@pytest.mark.parametrize(("quantity", "text"), [("2E+3", "2000"), ("0.001", "0.001")])
def test_quantity_is_plain_text_never_exponent_or_float(quantity, text):
    payload = build_payload("RM-1", "AUC1", Decimal(quantity), "KG", date(2026, 11, 20))

    assert payload["to_PurchaseReqnItem"][0]["RequestedQuantity"] == text


# --- Handshake ----------------------------------------------------------------------------------


def test_fetches_a_token_then_posts_with_it_and_the_api_key():
    session = FakeSession()

    result = send(session)

    assert result.ok and result.pr_number == "10000000" and result.error_message == ""
    (get_method, get_url, get_headers, get_timeout), post = session.calls
    assert (get_method, get_url) == ("GET", f"{SERVICE}/")
    assert get_headers["X-CSRF-Token"] == "Fetch" and get_headers["APIKey"] == KEY
    assert get_timeout == TIMEOUT_SECONDS
    assert post[0:2] == ("POST", f"{SERVICE}/A_PurchaseRequisitionHeader")
    assert post[2]["X-CSRF-Token"] == "tok-1" and post[2]["APIKey"] == KEY
    assert post[3] == PAYLOAD


def test_uses_the_mock_settings_by_default(settings):
    settings.MOCK_PR_BASE_URL = BASE + "/"
    settings.MOCK_API_KEY = KEY
    session = FakeSession()

    assert create_requisition(PAYLOAD, session=session).ok
    assert session.calls[0][1] == f"{SERVICE}/"


@pytest.mark.parametrize(("url", "key"), [("", KEY), (BASE, "")])
def test_without_settings_nothing_is_sent(settings, url, key):
    settings.MOCK_PR_BASE_URL = url
    settings.MOCK_API_KEY = key
    session = FakeSession()

    result = create_requisition(PAYLOAD, session=session)

    assert not result.ok and result.error_message == UNREACHABLE
    assert session.calls == []


# --- Failures (R-4): never raise, always a message ----------------------------------------------


def test_odata_error_shows_sap_text():
    result = send(FakeSession(post_answer=answer(400, odata_error("Material is required."))))

    assert not result.ok
    assert result.error_message == "Material is required."
    assert result.response == {"status": 400, "body": odata_error("Material is required.")}


@pytest.mark.parametrize("error", [requests.Timeout(), requests.ConnectionError()])
@pytest.mark.parametrize("step", ["GET", "POST"])
def test_network_error_or_timeout_is_unreachable(error, step):
    result = send(FakeSession(raise_on={step: error}))

    assert not result.ok and result.error_message == UNREACHABLE


@pytest.mark.parametrize(
    "post_answer",
    [
        answer(201, {"d": {}}),  # no number
        answer(201, {"d": None}),  # review #68: `d` that is not an object
        answer(201, {"d": "x"}),
        answer(201, ["not", "an", "object"]),
        answer(201, {"d": {"PurchaseRequisition": ""}}),
        answer(201, {"d": {"PurchaseRequisition": "1" * 21}}),  # longer than we store
        answer(201, text="not json"),
        answer(401, odata_error("API key missing")),  # configuration faults
        answer(403, None, {"X-CSRF-Token": "Required"}),
        answer(500, text="<html>oops</html>"),
    ],
)
def test_anything_else_is_not_accepted(post_answer):
    result = send(FakeSession(post_answer=post_answer))

    assert not result.ok and result.error_message == NOT_ACCEPTED


@pytest.mark.parametrize(
    "token_answer",
    [answer(200, {"d": {}}), answer(401, odata_error("API key missing"))],
)
def test_no_token_means_nothing_is_posted(token_answer):
    session = FakeSession(token_answer=token_answer)

    result = send(session)

    assert result.error_message == NOT_ACCEPTED
    assert [call[0] for call in session.calls] == ["GET"]


def test_the_api_key_is_never_in_the_stored_response():
    for session in [
        FakeSession(),
        FakeSession(post_answer=answer(400, odata_error("x"))),
        FakeSession(raise_on={"POST": requests.Timeout()}),
    ]:
        assert KEY not in repr(send(session).response)


# --- Base URL with or without the service path (#83, AC-64) ------------------------------------


@pytest.mark.parametrize(
    ("base_url", "expected_service"),
    [
        (BASE, SERVICE),
        (BASE + "/", SERVICE),
        (SERVICE, SERVICE),
        (SERVICE + "/", SERVICE),
        # Any other path is passed through unchanged: only an exact match is removed.
        (f"{BASE}/other", f"{BASE}/other/sap/opu/odata/sap/API_PURCHASEREQ_PROCESS_SRV"),
        (
            f"{BASE}/sap/opu/odata/sap/api_purchasereq_process_srv",
            f"{BASE}/sap/opu/odata/sap/api_purchasereq_process_srv"
            "/sap/opu/odata/sap/API_PURCHASEREQ_PROCESS_SRV",
        ),
    ],
)
def test_ac_64_base_url_with_or_without_the_service_path(settings, base_url, expected_service):
    settings.MOCK_PR_BASE_URL = base_url
    settings.MOCK_API_KEY = KEY
    session = FakeSession()

    assert create_requisition(PAYLOAD, session=session).ok

    assert [call[0:2] for call in session.calls] == [
        ("GET", f"{expected_service}/"),
        ("POST", f"{expected_service}/A_PurchaseRequisitionHeader"),
    ]


def test_ac_64_only_a_slash_still_counts_as_not_set(settings):
    settings.MOCK_PR_BASE_URL = "/"
    settings.MOCK_API_KEY = KEY
    session = FakeSession()

    result = create_requisition(PAYLOAD, session=session)

    assert not result.ok and result.error_message == UNREACHABLE
    assert result.response == {"error": "MOCK_PR_BASE_URL or key not set"}
    assert session.calls == []
