"""AC-32 (REQ-8, change request): safety stock is read from SAP during sync and reserved before
allocation. Stock 100, safety stock 30, order A needs 60, order B needs 20 → A available 70,
green; B available 10, red, shortage 10. Safety stock above stock → available 0. The tooltip
mentions it, with the amount, when it is above 0; /settings/ shows it read only.

Constructed data: safety stock is 0 for every material in the sandbox plants."""

from decimal import Decimal

import pytest

from tests.acceptance import builders
from tests.acceptance.support import Stock, days, one_component_order, read_page, shows_quantity

pytestmark = pytest.mark.xfail(strict=True, reason="Not built yet: #31")

ORDERS = [
    one_component_order("1000001", days(1), "RM-1", "60"),
    one_component_order("1000002", days(2), "RM-1", "20"),
]
SAFETY_NOTE = "Available = stock minus SAP safety stock of 30 PC."


def test_ac_32_safety_stock_is_reserved_before_allocation():
    stock = Stock("RM-1", Decimal("100"), safety_stock=Decimal("30"))

    outcome = builders.calculate(ORDERS, [stock])

    a = outcome.component("1000001")
    b = outcome.component("1000002")
    assert (a.status, a.available) == (builders.COVERED, Decimal("70"))
    assert (b.status, b.available, b.shortage) == (builders.SHORT, Decimal("10"), Decimal("10"))


@pytest.mark.parametrize(
    ("stock", "safety", "available"),
    [("20", "30", "0"), ("30", "30", "0"), ("100", "30", "70")],
)
def test_ac_32_available_never_drops_below_zero(stock, safety, available):
    outcome = builders.calculate(
        ORDERS[:1], [Stock("RM-1", Decimal(stock), safety_stock=Decimal(safety))]
    )

    assert outcome.component("1000001").available == Decimal(available)


def test_ac_32_sync_stores_safety_stock_and_the_tooltip_names_it(fakes, clock, client_as):
    fakes.sap.orders += ORDERS
    fakes.sap.stock.append(Stock("RM-1", Decimal("100"), safety_stock=Decimal("30")))
    client = client_as("Viewer")

    first = read_page(client.get("/orders/1000001/"))
    second = read_page(client.get("/orders/1000002/"))

    assert shows_quantity(first.row_with("RM-1"), Decimal("70"), "PC")
    assert SAFETY_NOTE in second.text


def test_ac_32_no_safety_note_when_safety_stock_is_zero(fakes, clock, client_as):
    fakes.sap.orders.append(one_component_order("1000001", days(1), "RM-1", "60"))
    fakes.sap.stock.append(Stock("RM-1", Decimal("10")))

    page = read_page(client_as("Viewer").get("/orders/1000001/"))

    assert "Short" in page.row_with("RM-1")
    assert "safety stock of" not in page.text


def test_ac_32_settings_show_safety_stock_read_only(client_as):
    page = read_page(client_as("Manager").get("/settings/"))

    assert "Safety stock" in page.text
    assert "From SAP" in page.text
    assert "Maintained in SAP, not here." in page.text
