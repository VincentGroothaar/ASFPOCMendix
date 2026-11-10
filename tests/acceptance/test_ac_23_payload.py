"""AC-23 (REQ-5): the payload sends the quantity converted to the stock unit, the stock unit,
and the delivery date = start date, or today if past. Fixed clock (today = 3 Nov 2026); the
fake mock records what the app posts."""

from decimal import Decimal

import pytest

from tests.acceptance import builders
from tests.acceptance.support import (
    PLANT,
    TODAY,
    Stock,
    days,
    one_component_order,
    parse_sap_date,
    posted_item,
)

pytestmark = pytest.mark.xfail(strict=True, reason="Not built yet: #27")


@pytest.mark.parametrize(("start", "delivery"), [(days(5), days(5)), (days(-3), TODAY)])
def test_ac_23_payload_is_in_stock_unit_with_the_delivery_date(
    fakes, clock, client_as, start, delivery
):
    fakes.sap.orders.append(one_component_order("1000101", start, "RM-1", "2", unit="KG"))
    fakes.sap.stock.append(Stock("RM-1", Decimal("1500"), unit="G", price=Decimal("0.001")))
    client = client_as("Planner")
    client.get("/orders/1000101/")

    client.post("/orders/1000101/requisitions/?material=RM-1", builders.requisition_form("0.5"))

    assert len(fakes.mock.posts) == 1
    item = posted_item(fakes.mock.posts[0])
    assert item["Material"] == "RM-1"
    assert item["Plant"] == PLANT
    assert isinstance(item["RequestedQuantity"], str)  # Decimal as string, never a float
    assert Decimal(item["RequestedQuantity"]) == Decimal("500")
    assert item["BaseUnit"] == "G"
    assert parse_sap_date(item["DeliveryDate"]) == delivery
