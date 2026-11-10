"""AC-28 (REQ-6): the dashboard shows the red order count, shortage per material with affected
orders, shortage per order, and unit mismatches separately, matching the order list.
Constructed snapshot."""

import re
from decimal import Decimal

import pytest

from tests.acceptance.support import (
    Component,
    Order,
    Stock,
    days,
    one_component_order,
    read_page,
    shows_quantity,
)

pytestmark = pytest.mark.xfail(strict=True, reason="Not built yet: #30")


def load_plant(sap) -> None:
    sap.orders += [
        one_component_order("1000101", days(1), "RM-SHORT", "100"),  # Short by 30
        one_component_order("1000102", days(2), "RM-SHORT", "20"),  # Short by 20
        one_component_order("1000103", days(3), "RM-LOW", "100"),  # Low cover
        Order(
            "1000104",
            days(4),
            [
                Component("RM-COVER", Decimal("100"), item="0001"),
                Component("RM-KG", Decimal("5"), unit="PC", item="0002"),  # unit mismatch
            ],
        ),
    ]
    sap.stock += [
        Stock("RM-SHORT", Decimal("70")),
        Stock("RM-LOW", Decimal("104")),
        Stock("RM-COVER", Decimal("500")),
        Stock("RM-KG", Decimal("50"), unit="KG"),
    ]


def count_after(label: str, text: str) -> int:
    match = re.search(re.escape(label) + r"\D*(\d+)", text)
    assert match, f"No count after {label!r}"
    return int(match.group(1))


def test_ac_28_dashboard_matches_the_order_list(fakes, clock, client_as):
    load_plant(fakes.sap)
    client = client_as("Viewer")

    dashboard = read_page(client.get("/dashboard/"))
    orders = read_page(client.get("/orders/"))

    assert count_after("Red orders", dashboard.text) == 2
    assert count_after("Short", orders.text) == 2  # the Short tile on the order list

    material_row = dashboard.row_with("RM-SHORT", "1000101")
    assert "1000102" in material_row
    assert shows_quantity(material_row, Decimal("50"), "PC")  # 30 + 20, in the stock unit

    assert dashboard.has_row_with("1000101")
    assert dashboard.has_row_with("1000102")
    assert "Unit mismatch" in dashboard.text
    assert "Unit mismatch lines are excluded from component counts." in dashboard.text


def test_ac_28_browser_dashboard_renders(fakes, running_clock, browser_as):
    from playwright.sync_api import expect

    load_plant(fakes.sap)

    page = browser_as("/dashboard/", role="Viewer")

    expect(page.get_by_role("heading", name="Shortage dashboard")).to_be_visible()
    expect(page.get_by_text("Red orders")).to_be_visible()
    expect(page.get_by_text("RM-SHORT").first).to_be_visible()
