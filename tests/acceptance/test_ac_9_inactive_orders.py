"""AC-9 (REQ-1): an order no longer released after a sync is marked inactive, disappears from
the list, and keeps its requisitions. Sync, create a requisition, sync without that order."""

import pytest

from tests.acceptance import builders
from tests.acceptance.support import PLANT, Stock, days, one_component_order, read_page

pytestmark = pytest.mark.xfail(strict=True, reason="Not built yet: #29")


def test_ac_9_order_gone_from_sap_leaves_the_list_but_keeps_requisitions(fakes, clock, client_as):
    fakes.sap.orders += [
        one_component_order("1000101", days(1), "RM-1", "100"),
        one_component_order("1000102", days(2), "RM-2", "10"),
    ]
    fakes.sap.stock += [Stock("RM-1", 40), Stock("RM-2", 100)]
    planner = client_as("Planner")
    planner.get("/orders/")
    planner.post("/orders/1000101/requisitions/?material=RM-1", builders.requisition_form("60"))

    fakes.sap.orders = [order for order in fakes.sap.orders if order.number != "1000101"]
    planner.post(f"/plants/{PLANT}/refresh/")

    orders_page = read_page(planner.get("/orders/"))
    assert "1000101" not in orders_page.text
    assert "1000102" in orders_page.text
    assert [(r.order, r.material) for r in builders.requisitions()] == [("1000101", "RM-1")]
    assert read_page(planner.get("/requisitions/")).has_row_with("1000101", "RM-1")
