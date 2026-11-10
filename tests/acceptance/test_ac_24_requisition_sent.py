"""AC-24 (REQ-5): on success the PR number is stored and shown, the button becomes a "PR sent"
label that opens the requisition with PR number and quantity, and a second request for the
same order + material is refused (INV-7). Acceptance test against the local mock."""

import os
import re
from decimal import Decimal

import pytest
import requests

from tests.acceptance import builders
from tests.acceptance.support import (
    MIXED_ORDER,
    MOCK_SERVICE,
    load_mixed_order,
    read_page,
    shows_quantity,
    sync,
)

pytestmark = pytest.mark.xfail(strict=True, reason="Not built yet: #29")


def test_ac_24_successful_requisition_against_the_local_mock(fakes, clock, client_as, live_mock):
    load_mixed_order(fakes.sap)
    for stock in fakes.sap.stock:
        stock.price = Decimal("1")  # below the approval limit
    planner = client_as("Planner")
    sync()
    create = f"/orders/{MIXED_ORDER}/requisitions/?material=RM-SHORT"

    planner.post(create, builders.requisition_form("30"))

    [requisition] = builders.requisitions()
    assert requisition.status == builders.SENT
    assert re.fullmatch(r"\d{8}", requisition.pr_number)

    in_mock = requests.get(
        f"{live_mock}{MOCK_SERVICE}/A_PurchaseRequisitionHeader('{requisition.pr_number}')",
        headers={"APIKey": os.environ["MOCK_API_KEY"], "Accept": "application/json"},
        timeout=10,
    )
    assert in_mock.status_code == 200

    detail = read_page(planner.get(f"/orders/{MIXED_ORDER}/"))
    assert "PR sent" in detail.row_with("RM-SHORT")
    assert not re.search(r"\bRequest\b", detail.row_with("RM-SHORT"))

    requisition_page = read_page(planner.get(f"/requisitions/{requisition.id}/"))
    assert requisition.pr_number in requisition_page.text
    assert shows_quantity(requisition_page.text, Decimal("30"), "PC")

    second = planner.post(create, builders.requisition_form("30"))
    assert second.status_code in (200, 400, 403, 409, 422)
    assert len(builders.requisitions()) == 1
