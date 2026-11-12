"""INV-4: the app never sends a write request to SAP; the requisition endpoint is the only POST
target. The SAP read client exposes no write method, and a full flow (sync, refresh, create)
sends only GETs to SAP."""

import inspect
from decimal import Decimal
from urllib.parse import urlparse

import pytest

from tests.acceptance import builders
from tests.acceptance.support import MIXED_ORDER, MOCK_URL, SAP_URL, load_mixed_order


def test_inv_4_sap_read_client_exposes_only_reads():
    from sap.client import ODataClient

    methods = [
        name
        for name, member in inspect.getmembers(ODataClient, inspect.isfunction)
        if not name.startswith("_")
    ]

    assert methods
    for name in methods:
        assert not any(w in name.lower() for w in ("post", "put", "patch", "delete", "merge"))


@pytest.mark.xfail(strict=True, reason="Not built yet: #25 (/orders/ and Refresh)")
def test_inv_4_full_flow_sends_only_gets_to_sap(fakes, clock, client_as):
    load_mixed_order(fakes.sap)
    for stock in fakes.sap.stock:
        stock.price = Decimal("1")
    planner = client_as("Planner")

    planner.get("/orders/")
    planner.post("/plants/AUC1/refresh/")
    planner.post(
        f"/orders/{MIXED_ORDER}/requisitions/?material=RM-SHORT", builders.requisition_form("30")
    )

    sap_host, mock_host = urlparse(SAP_URL).netloc, urlparse(MOCK_URL).netloc
    assert fakes.sap.calls, "Expected the app to read SAP"
    assert {r.method for r in fakes.http.sent if r.host == sap_host} == {"GET"}
    assert {r.host for r in fakes.http.sent if r.method != "GET"} == {mock_host}
