"""AC-22 (REQ-5): the confirm step prefills the shortage for a short component, and
(100 + buffer)% × open requirement − available for a low cover component (requirement 100,
available 104, buffer 10 → 6), rounded up to 3 decimals (requirement 0.333, available 0.35,
buffer 12.25 → 0.0237925 → 0.024); 0, negative, non-numeric and 4-decimal values are rejected
with a message."""

from decimal import Decimal

import pytest

from tests.acceptance import builders
from tests.acceptance.support import (
    MIXED_ORDER,
    Stock,
    days,
    load_mixed_order,
    one_component_order,
    read_page,
)

CONFIRM = f"/orders/{MIXED_ORDER}/requisitions/"


@pytest.mark.xfail(strict=True, reason="Not built yet: #27")
@pytest.mark.parametrize(("material", "prefill"), [("RM-SHORT", "30"), ("RM-LOW", "6")])
def test_ac_22_confirm_step_prefills_the_quantity(fakes, clock, client_as, material, prefill):
    load_mixed_order(fakes.sap)

    page = read_page(client_as("Planner").get(CONFIRM, {"material": material}))

    assert Decimal(prefill) in page.input_decimals()


@pytest.mark.xfail(strict=True, reason="Not built yet: #34")
def test_ac_22_low_cover_prefill_rounds_up_to_3_decimals(fakes, clock, client_as):
    fakes.sap.orders.append(one_component_order("1000101", days(1), "RM-1", "0.333", "KG"))
    fakes.sap.stock.append(Stock("RM-1", Decimal("0.35"), unit="KG"))
    client_as("Manager").post("/settings/", builders.buffer_form("12.25"))

    page = read_page(
        client_as("Planner").get("/orders/1000101/requisitions/", {"material": "RM-1"})
    )

    assert Decimal("0.024") in page.input_decimals()


@pytest.mark.xfail(strict=True, reason="Not built yet: #27")
@pytest.mark.parametrize("quantity", ["0", "-5", "abc", "1.2345", ""])
def test_ac_22_invalid_quantities_are_rejected(fakes, clock, client_as, quantity):
    load_mixed_order(fakes.sap)
    client = client_as("Planner")
    client.get(f"/orders/{MIXED_ORDER}/")

    response = client.post(f"{CONFIRM}?material=RM-SHORT", builders.requisition_form(quantity))

    assert response.status_code in (200, 400, 422)
    assert builders.requisitions() == []
    assert fakes.mock.posts == []
