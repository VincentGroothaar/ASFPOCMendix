"""AC-26 (REQ-5): the requisition list shows number, order, material, quantity, unit, delivery
date, user, time and outcome for every attempt."""

from decimal import Decimal

import pytest

from tests.acceptance import builders
from tests.acceptance.support import (
    MIXED_ORDER,
    load_mixed_order,
    read_page,
    shows_quantity,
    sync,
)

pytestmark = pytest.mark.xfail(strict=True, reason="Not built yet: #29")


def test_ac_26_every_attempt_is_listed_with_its_details(fakes, clock, client_as):
    load_mixed_order(fakes.sap)  # starts tomorrow, 04 Nov
    for stock in fakes.sap.stock:
        stock.price = Decimal("1")
    planner = client_as("Planner", "pat")
    sync()
    fakes.mock.error = "Property 'PurchasingGroup' is required (item 1)."
    planner.post(
        f"/orders/{MIXED_ORDER}/requisitions/?material=RM-SHORT", builders.requisition_form("30")
    )
    fakes.mock.error = None
    planner.post(
        f"/orders/{MIXED_ORDER}/requisitions/?material=RM-LOW", builders.requisition_form("6")
    )
    failed, sent = builders.requisitions()

    page = read_page(client_as("Viewer").get("/requisitions/"))

    sent_row = page.row_with(f"REQ-{sent.id}")
    for expected in (sent.pr_number, MIXED_ORDER, "RM-LOW", "04 Nov", "pat", "03 Nov 10:00"):
        assert expected in sent_row, f"{expected!r} missing in {sent_row!r}"
    assert "PR sent" in sent_row
    assert shows_quantity(sent_row, Decimal("6"), "PC")

    failed_row = page.row_with(f"REQ-{failed.id}")
    for expected in (MIXED_ORDER, "RM-SHORT", "04 Nov", "pat", "03 Nov 10:00", "PR failed"):
        assert expected in failed_row, f"{expected!r} missing in {failed_row!r}"
    assert shows_quantity(failed_row, Decimal("30"), "PC")
