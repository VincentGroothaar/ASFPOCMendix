"""Write client for purchase requisitions: the only POST the app ever sends (INV-4).

It talks to the purchase requisition mock (`mock_pr`, #8), which behaves like SAP's
`API_PURCHASEREQ_PROCESS_SRV`: first a GET that fetches a CSRF token, then a POST with that
token. The address and key come only from MOCK_PR_BASE_URL and MOCK_API_KEY (INV-3), never from
SAP_BASE_URL.

The client never raises for HTTP or network problems. Every outcome comes back as a
RequisitionResult, so the caller can store every attempt (ARCHITECTURE.md, "Create requisition").
"""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

import requests
from django.conf import settings

SERVICE_PATH = "/sap/opu/odata/sap/API_PURCHASEREQ_PROCESS_SRV"
ENTITY_SET = "A_PurchaseRequisitionHeader"
TIMEOUT_SECONDS = 10

# Fields the cockpit cannot derive from the order: the most common sandbox values
# (mock_pr/README.md, "Header constants for the Cockpit").
HEADER_CONSTANTS = {"PurchaseRequisitionType": "NB"}
ITEM_CONSTANTS = {"PurchasingGroup": "001"}

# Longest requisition number the cockpit stores (Requisition.pr_number). SAP's own is 10.
MAX_PR_NUMBER_LENGTH = 20

UNREACHABLE = "The requisition service could not be reached. Try again."
NOT_ACCEPTED = "The requisition service did not accept the request. Try again."


@dataclass(frozen=True)
class RequisitionResult:
    """The outcome of one send. Exactly one of `pr_number` and `error_message` is set.

    `response` holds the HTTP status and body for the record (never the API key).
    """

    pr_number: str | None
    error_message: str = ""
    response: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.pr_number is not None


def build_payload(
    material: str, plant: str, quantity: Decimal, unit: str, delivery_date: date
) -> dict:
    """The requisition body: one header with one item, quantity in the stock unit (spec.md)."""
    item = {
        "Material": material,
        "Plant": plant,
        # OData V2 sends decimals as plain text: never a float, never "1E+3".
        "RequestedQuantity": format(quantity, "f"),
        "BaseUnit": unit,
        "DeliveryDate": odata_date(delivery_date),
        **ITEM_CONSTANTS,
    }
    return {**HEADER_CONSTANTS, "to_PurchaseReqnItem": [item]}


def odata_date(value: date) -> str:
    """A date as OData V2 JSON writes it: /Date(<milliseconds since 1970>)/ at midnight UTC."""
    moment = datetime(value.year, value.month, value.day, tzinfo=UTC)
    return f"/Date({int(moment.timestamp() * 1000)})/"


def create_requisition(
    payload: dict,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    session: requests.Session | None = None,
) -> RequisitionResult:
    """Send one requisition to the mock: fetch a CSRF token, then POST the payload.

    Without arguments the address and key come from settings. Returns the PR number on
    success, or an error message: SAP's own text for an OData error, a fixed text otherwise.
    """
    base_url = (settings.MOCK_PR_BASE_URL if base_url is None else base_url).rstrip("/")
    api_key = settings.MOCK_API_KEY if api_key is None else api_key
    if not base_url or not api_key:
        return RequisitionResult(None, UNREACHABLE, {"error": "MOCK_PR_BASE_URL or key not set"})

    session = session or requests.Session()
    # The key lives only in the session headers, so it never lands in `response` or a traceback.
    session.headers.update({"APIKey": api_key, "Accept": "application/json"})
    service_url = f"{base_url}{SERVICE_PATH}"
    try:
        token_response = session.get(
            f"{service_url}/", headers={"X-CSRF-Token": "Fetch"}, timeout=TIMEOUT_SECONDS
        )
        token = token_response.headers.get("X-CSRF-Token", "")
        if not token_response.ok or not token or token.lower() == "required":
            return _not_accepted(token_response)
        response = session.post(
            f"{service_url}/{ENTITY_SET}",
            json=payload,
            headers={"X-CSRF-Token": token},
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as error:
        return RequisitionResult(None, UNREACHABLE, {"error": type(error).__name__})
    return _read_answer(response)


def _read_answer(response: requests.Response) -> RequisitionResult:
    """Turn the mock's answer to the POST into a RequisitionResult."""
    record = _record(response)
    if response.status_code in (401, 403):
        # A wrong key or CSRF token is a configuration fault, not something to show planners.
        return RequisitionResult(None, NOT_ACCEPTED, record)
    body = record.get("body")
    if not response.ok:
        message = _odata_error_message(body)
        return RequisitionResult(None, message or NOT_ACCEPTED, record)
    number = body.get("d", {}).get("PurchaseRequisition") if isinstance(body, dict) else None
    if not isinstance(number, str) or not number or len(number) > MAX_PR_NUMBER_LENGTH:
        return RequisitionResult(None, NOT_ACCEPTED, record)
    return RequisitionResult(number, "", record)


def _not_accepted(response: requests.Response) -> RequisitionResult:
    """The token fetch failed: the mock refused us before we could send anything."""
    return RequisitionResult(None, NOT_ACCEPTED, _record(response))


def _record(response: requests.Response) -> dict:
    """The HTTP status and body of an answer, for storing with the attempt."""
    try:
        body = response.json()
    except ValueError:
        body = response.text
    return {"status": response.status_code, "body": body}


def _odata_error_message(body: object) -> str:
    """SAP's error text from an OData V2 error body, or "" when the body is not one."""
    if not isinstance(body, dict):
        return ""
    error = body.get("error")
    message = error.get("message") if isinstance(error, dict) else None
    value = message.get("value") if isinstance(message, dict) else None
    return value if isinstance(value, str) else ""
