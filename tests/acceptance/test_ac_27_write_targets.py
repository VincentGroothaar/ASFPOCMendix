"""AC-27 (REQ-5 / INV-3 / INV-4): requisitions are sent only to MOCK_PR_BASE_URL with a CSRF
token and the APIKey header; no request ever writes to SAP_BASE_URL. Fake SAP and fake mock
record every request; plus a check that the SAP read client has no write method."""

import inspect
from decimal import Decimal
from urllib.parse import urlparse

from tests.acceptance import builders
from tests.acceptance.support import (
    MIXED_ORDER,
    MOCK_KEY,
    MOCK_URL,
    SAP_URL,
    FakeMock,
    load_mixed_order,
    sync,
)

WRITE_WORDS = ("post", "put", "patch", "delete", "merge", "create", "update", "write")


def test_ac_27_sap_read_client_has_no_write_method():
    from sap.client import ODataClient

    public = [name for name, _ in inspect.getmembers(ODataClient) if not name.startswith("_")]

    assert public, "ODataClient should have read methods"
    assert not [name for name in public if any(word in name.lower() for word in WRITE_WORDS)]


def test_ac_27_only_the_mock_receives_writes_with_csrf_and_api_key(fakes, clock, client_as):
    load_mixed_order(fakes.sap)
    for stock in fakes.sap.stock:
        stock.price = Decimal("1")
    planner = client_as("Planner")
    sync()

    planner.post(
        f"/orders/{MIXED_ORDER}/requisitions/?material=RM-SHORT", builders.requisition_form("30")
    )

    writes = [r for r in fakes.http.sent if r.method not in ("GET", "HEAD", "OPTIONS")]
    assert len(writes) == 1
    [post] = writes
    assert post.host == urlparse(MOCK_URL).netloc
    assert post.path.endswith("/A_PurchaseRequisitionHeader")
    assert post.headers.get("X-CSRF-Token") == FakeMock.TOKEN
    assert post.headers.get("APIKey") == MOCK_KEY
    sap_host = urlparse(SAP_URL).netloc
    assert all(r.method == "GET" for r in fakes.http.sent if r.host == sap_host)
    assert builders.requisitions()[0].status == builders.SENT
