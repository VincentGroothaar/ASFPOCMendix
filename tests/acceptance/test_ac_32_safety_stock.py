"""AC-32 (REQ-8, change request): safety stock is read from SAP during sync and reserved before
allocation. Stock 100, safety stock 30, order A needs 60, order B needs 20 → A available 70,
green; B available 10, red, shortage 10. Safety stock above stock → available 0. The tooltip
mentions it, with the amount, when it is above 0; /settings/ shows it read only.

Constructed data: safety stock is 0 for every material in the sandbox plants. The tooltip is
checked in a browser after hovering, as in AC-20, because it may be loaded on demand."""

from decimal import Decimal

import pytest

from tests.acceptance import builders
from tests.acceptance.support import (
    Stock,
    days,
    one_component_order,
    read_page,
    shows_quantity,
    sync,
)

ORDERS = [
    one_component_order("1000001", days(1), "RM-1", "60"),
    one_component_order("1000002", days(2), "RM-1", "20"),
]
SHORT_TEXT = (
    "Short: available stock is below the open requirement, after earlier orders take their share."
)
SAFETY_NOTE = "Available = stock minus SAP safety stock of 30 PC."


@pytest.mark.xfail(strict=True, reason="Not built yet: #31")
def test_ac_32_safety_stock_is_reserved_before_allocation():
    stock = Stock("RM-1", Decimal("100"), safety_stock=Decimal("30"))

    outcome = builders.calculate(ORDERS, [stock])

    a = outcome.component("1000001")
    b = outcome.component("1000002")
    assert (a.status, a.available) == (builders.COVERED, Decimal("70"))
    assert (b.status, b.available, b.shortage) == (builders.SHORT, Decimal("10"), Decimal("10"))


@pytest.mark.xfail(strict=True, reason="Not built yet: #31")
@pytest.mark.parametrize(
    ("stock", "safety", "available"),
    [("20", "30", "0"), ("30", "30", "0"), ("100", "30", "70")],
)
def test_ac_32_available_never_drops_below_zero(stock, safety, available):
    outcome = builders.calculate(
        ORDERS[:1], [Stock("RM-1", Decimal(stock), safety_stock=Decimal(safety))]
    )

    assert outcome.component("1000001").available == Decimal(available)


@pytest.mark.xfail(strict=True, reason="Not built yet: #31")
def test_ac_32_sync_stores_safety_stock(fakes, clock, client_as):
    fakes.sap.orders += ORDERS
    fakes.sap.stock.append(Stock("RM-1", Decimal("100"), safety_stock=Decimal("30")))
    sync()

    page = read_page(client_as("Viewer").get("/orders/1000001/"))

    assert shows_quantity(page.row_with("RM-1"), Decimal("70"), "PC")


def hover_short_tooltip(page):
    page.get_by_role("button", name="What does Short mean?").first.hover()


@pytest.mark.xfail(strict=True, reason="Not built yet: #31")
def test_ac_32_browser_short_tooltip_names_the_safety_stock(fakes, running_clock, browser_as):
    from playwright.sync_api import expect

    fakes.sap.orders += ORDERS
    fakes.sap.stock.append(Stock("RM-1", Decimal("100"), safety_stock=Decimal("30")))
    sync()

    page = browser_as("/orders/1000002/", role="Viewer")
    hover_short_tooltip(page)

    expect(page.get_by_text(SAFETY_NOTE, exact=False)).to_be_visible()


def test_ac_32_browser_no_safety_note_when_safety_stock_is_zero(fakes, running_clock, browser_as):
    from playwright.sync_api import expect

    fakes.sap.orders.append(one_component_order("1000001", days(1), "RM-1", "60"))
    fakes.sap.stock.append(Stock("RM-1", Decimal("10")))
    sync()

    page = browser_as("/orders/1000001/", role="Viewer")
    hover_short_tooltip(page)

    expect(page.get_by_text(SHORT_TEXT, exact=True)).to_be_visible()
    expect(page.get_by_text("safety stock of", exact=False)).to_have_count(0)


@pytest.mark.xfail(strict=True, reason="Not built yet: #34")
def test_ac_32_settings_show_safety_stock_read_only(client_as):
    page = read_page(client_as("Manager").get("/settings/"))

    assert "Safety stock" in page.text
    assert "From SAP" in page.text
    assert "Maintained in SAP, not here." in page.text
