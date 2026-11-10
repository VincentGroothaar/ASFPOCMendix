"""AC-10 (REQ-2): each component shows material, description, open requirement (as Required)
and unit; a partly withdrawn component shows required − withdrawn.

The first test reads the live SAP sandbox and asserts the rule, not fixed numbers (D-19).
The sandbox has no withdrawn quantities in AUC1, so the second test uses constructed data.
"""

from decimal import Decimal

import pytest

from tests.acceptance.support import (
    PLANT,
    Component,
    Order,
    Stock,
    days,
    live_released_orders,
    read_live_sap,
    read_page,
    shows_quantity,
    sync,
)

pytestmark = pytest.mark.xfail(strict=True, reason="Not built yet: #26")


def test_ac_10_components_match_sap_on_one_live_order(live_sap, client_as):
    order = live_released_orders(PLANT, top=1)[0]
    lines = order["to_ProductionOrderComponent"]["results"]
    materials = sorted({line["Material"] for line in lines})
    descriptions = {
        row["Product"]: row["ProductDescription"]
        for row in read_live_sap(
            "API_PRODUCT_SRV/A_ProductDescription",
            {
                "$filter": "Language eq 'EN' and ("
                + " or ".join(f"Product eq '{m}'" for m in materials)
                + ")"
            },
        )
    }
    client = client_as("Viewer")
    client.get("/orders/", {"plant": PLANT})

    page = read_page(client.get(f"/orders/{order['ManufacturingOrder']}/"))

    for line in lines:
        row = page.row_with(line["Material"])
        open_requirement = Decimal(line["RequiredQuantity"]) - Decimal(line["WithdrawnQuantity"])
        assert descriptions[line["Material"]] in row
        assert shows_quantity(row, open_requirement, line["BaseUnit"]), row


def test_ac_10_partly_withdrawn_component_shows_the_open_requirement(fakes, clock, client_as):
    fakes.sap.orders.append(
        Order("1000101", days(1), [Component("RM-1", Decimal("10"), withdrawn=Decimal("4"))])
    )
    fakes.sap.stock.append(Stock("RM-1", Decimal("100"), description="Steel frame"))

    sync()

    page = read_page(client_as("Viewer").get("/orders/1000101/"))

    row = page.row_with("RM-1")
    assert "Steel frame" in row
    assert shows_quantity(row, Decimal("6"), "PC"), row
    assert not shows_quantity(row, Decimal("10"), "PC"), row
