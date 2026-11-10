"""Tests of the mock over HTTP, against a real Postgres (in a test schema, dropped afterwards)."""

import os

import psycopg
import pytest
from fastapi.testclient import TestClient

from mock_pr.main import SERVICE_PATH, create_app
from mock_pr.store import RequisitionStore

API_KEY = "test-api-key"
TEST_SCHEMA = "mock_pr_test"
HEADERS_URL = f"{SERVICE_PATH}/A_PurchaseRequisitionHeader"


def valid_requisition() -> dict:
    """The shape the Cockpit sends: one header with one item."""
    return {
        "PurchaseRequisitionType": "NB",
        "to_PurchaseReqnItem": [
            {
                "Material": "MZ-RM-C990-01",
                "Plant": "AUC1",
                "RequestedQuantity": "12.5",
                "BaseUnit": "PC",
                "DeliveryDate": "/Date(1762646400000)/",
                "PurchasingGroup": "001",
            }
        ],
    }


@pytest.fixture
def database_url() -> str:
    return os.environ["DATABASE_URL"]


@pytest.fixture
def client(database_url):
    RequisitionStore(database_url, TEST_SCHEMA).drop_schema()
    with TestClient(create_app(database_url, API_KEY, TEST_SCHEMA)) as test_client:
        test_client.headers["APIKey"] = API_KEY
        yield test_client
    RequisitionStore(database_url, TEST_SCHEMA).drop_schema()


def fetch_token(client: TestClient) -> str:
    response = client.get(f"{SERVICE_PATH}/", headers={"X-CSRF-Token": "Fetch"})
    assert response.status_code == 200
    return response.headers["X-CSRF-Token"]


def post_requisition(client: TestClient, body: dict):
    return client.post(HEADERS_URL, json=body, headers={"X-CSRF-Token": fetch_token(client)})


def error_message(response) -> str:
    error = response.json()["error"]
    assert error["message"]["lang"] == "en"
    return error["message"]["value"]


@pytest.mark.parametrize("headers", [{}, {"APIKey": "wrong"}, {"APIKey": b"r\xe9view"}])
def test_missing_or_wrong_api_key_returns_401(client, headers) -> None:
    client.headers.pop("APIKey")

    for response in [
        client.get(f"{SERVICE_PATH}/$metadata", headers=headers),
        client.post(HEADERS_URL, json=valid_requisition(), headers=headers),
    ]:
        assert response.status_code == 401
        assert "APIKey" in error_message(response)


def test_metadata_is_the_saved_sap_metadata(client) -> None:
    response = client.get(f"{SERVICE_PATH}/$metadata")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    assert "A_PurchaseRequisitionHeaderType" in response.text


def test_csrf_fetch_returns_a_token_in_header_and_cookie(client) -> None:
    response = client.get(f"{SERVICE_PATH}/$metadata", headers={"X-CSRF-Token": "Fetch"})

    token = response.headers["X-CSRF-Token"]
    assert token
    assert response.cookies.get("sap-XSRF_mock") == token


@pytest.mark.parametrize("token", [None, "made-up.token", b"a.\xe9"])
def test_post_without_a_valid_csrf_token_returns_403(client, token) -> None:
    headers = {} if token is None else {"X-CSRF-Token": token}

    response = client.post(HEADERS_URL, json=valid_requisition(), headers=headers)

    assert response.status_code == 403
    assert response.headers["X-CSRF-Token"] == "Required"
    assert "CSRF" in error_message(response)


def test_valid_post_returns_201_with_a_requisition_number(client) -> None:
    response = post_requisition(client, valid_requisition())

    assert response.status_code == 201
    header = response.json()["d"]
    number = header["PurchaseRequisition"]
    assert len(number) == 8 and number.isdigit()
    assert header["PurchaseRequisitionType"] == "NB"
    assert response.headers["Location"].endswith(f"A_PurchaseRequisitionHeader('{number}')")

    item = header["to_PurchaseReqnItem"]["results"][0]
    assert item["PurchaseRequisition"] == number
    assert item["PurchaseRequisitionItem"] == "10"
    assert item["Material"] == "MZ-RM-C990-01"
    assert item["RequestedQuantity"] == "12.5"


def test_items_are_numbered_10_20(client) -> None:
    body = valid_requisition()
    body["to_PurchaseReqnItem"] = {"results": body["to_PurchaseReqnItem"] * 2}

    items = post_requisition(client, body).json()["d"]["to_PurchaseReqnItem"]["results"]

    assert [item["PurchaseRequisitionItem"] for item in items] == ["10", "20"]


def test_two_posts_get_different_numbers(client) -> None:
    first = post_requisition(client, valid_requisition()).json()["d"]["PurchaseRequisition"]
    second = post_requisition(client, valid_requisition()).json()["d"]["PurchaseRequisition"]

    assert first != second


def test_numbers_and_requisitions_survive_a_restart(client, database_url) -> None:
    first = post_requisition(client, valid_requisition()).json()["d"]["PurchaseRequisition"]

    with TestClient(create_app(database_url, API_KEY, TEST_SCHEMA)) as restarted:
        restarted.headers["APIKey"] = API_KEY
        second = post_requisition(restarted, valid_requisition()).json()["d"]
        read_back = restarted.get(f"{HEADERS_URL}('{first}')")

    assert int(second["PurchaseRequisition"]) > int(first)
    assert read_back.status_code == 200
    # The numbers come from a sequence in the database, not from memory in the process.
    with psycopg.connect(database_url) as connection:
        row = connection.execute(
            "SELECT last_value FROM pg_sequences WHERE schemaname = %s", (TEST_SCHEMA,)
        ).fetchone()
    assert row == (int(second["PurchaseRequisition"]),)


def test_a_requisition_can_be_read_back_by_number(client) -> None:
    created = post_requisition(client, valid_requisition()).json()["d"]
    number = created["PurchaseRequisition"]

    response = client.get(f"{HEADERS_URL}('{number}')")

    assert response.status_code == 200
    assert response.json()["d"] == created


def test_reading_an_unknown_number_returns_404(client) -> None:
    response = client.get(f"{HEADERS_URL}('99999999')")

    assert response.status_code == 404
    assert "99999999" in error_message(response)


def without_item_field(name: str) -> dict:
    body = valid_requisition()
    del body["to_PurchaseReqnItem"][0][name]
    return body


def with_item_field(name: str, value: object) -> dict:
    body = valid_requisition()
    body["to_PurchaseReqnItem"][0][name] = value
    return body


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (without_item_field("PurchasingGroup"), "Property 'PurchasingGroup' is required"),
        (with_item_field("Colour", "red"), "Property 'Colour' is invalid"),
        (with_item_field("RequestedQuantity", 12.5), "RequestedQuantity"),
        (with_item_field("Plant", "AUC12"), "at most 4 characters"),
        (with_item_field("Material", 123), "expected text"),
        (with_item_field("Material", "AB\u0000C"), "not allowed"),
    ],
    ids=[
        "missing required field",
        "unknown property",
        "wrong type",
        "too long",
        "number for text",
        "NUL character",
    ],
)
def test_invalid_payload_returns_400_with_an_odata_error(client, body, expected) -> None:
    response = post_requisition(client, body)

    assert response.status_code == 400
    assert expected in error_message(response)


def test_a_surrogate_in_a_property_name_returns_400(client) -> None:
    response = client.post(
        HEADERS_URL,
        content=b'{"\\ud800": "x"}',
        headers={"X-CSRF-Token": fetch_token(client), "Content-Type": "application/json"},
    )

    assert response.status_code == 400
    assert "Property '?' is invalid" in error_message(response)


@pytest.mark.parametrize(
    "content",
    [b"{not json", b'{"a": \xff}', b"[" * 100000, b"1" * 5000],
    ids=["broken JSON", "not UTF-8", "nested too deeply", "number too long"],
)
def test_invalid_json_returns_400(client, content) -> None:
    response = client.post(
        HEADERS_URL,
        content=content,
        headers={"X-CSRF-Token": fetch_token(client), "Content-Type": "application/json"},
    )

    assert response.status_code == 400
    assert "JSON" in error_message(response)


def test_an_invalid_post_does_not_use_up_a_number(client) -> None:
    first = post_requisition(client, valid_requisition()).json()["d"]["PurchaseRequisition"]
    post_requisition(client, without_item_field("Material"))
    second = post_requisition(client, valid_requisition()).json()["d"]["PurchaseRequisition"]

    assert int(second) == int(first) + 1
