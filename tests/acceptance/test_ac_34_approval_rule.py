"""AC-34 (REQ-10, change request): a requisition whose value (quantity in stock unit × price per
stock unit) is above 10,000 in the plant's currency, or whose material has no price, is stored
as awaiting approval and not sent. Value exactly 10,000 is sent.

Unit tests on `needs_approval` at, below and above the limit and without a price, and tests
where the fake mock confirms that no POST was received."""

from decimal import Decimal

import pytest

from tests.acceptance import builders
from tests.acceptance.support import (
    ABOVE_LIMIT_CREATE,
    Stock,
    above_limit_plant,
    days,
    one_component_order,
    sync,
)

# Marked per test, not for the module: the at-the-limit case is already sent before the change
# request (#27 sends every requisition), so only the approval parts wait for #32.
NOT_BUILT = pytest.mark.xfail(strict=True, reason="Not built yet: #32")


@NOT_BUILT
def test_ac_34_approval_limit_is_10000():
    from cockpit.services.requisitions import APPROVAL_LIMIT

    assert APPROVAL_LIMIT == Decimal("10000")


@NOT_BUILT
@pytest.mark.parametrize(
    ("quantity", "price", "needed"),
    [
        ("50", "200", False),  # exactly 10,000
        ("49.999", "200", False),  # just below
        ("50.001", "200", True),  # just above
        ("1", None, True),  # no price
    ],
)
def test_ac_34_needs_approval(quantity, price, needed):
    from cockpit.services.requisitions import needs_approval

    price_value = Decimal(price) if price is not None else None

    assert needs_approval(Decimal(quantity), price_value) is needed


@pytest.mark.parametrize(
    ("quantity", "status"),
    [pytest.param("60", "awaiting", marks=NOT_BUILT), ("50", "sent")],
)
def test_ac_34_above_the_limit_waits_and_at_the_limit_is_sent(
    fakes, clock, client_as, quantity, status
):
    above_limit_plant(fakes.sap)
    sync()

    client_as("Planner").post(ABOVE_LIMIT_CREATE, builders.requisition_form(quantity))

    [requisition] = builders.requisitions()
    if status == "awaiting":
        assert requisition.status == builders.AWAITING_APPROVAL
        assert fakes.mock.posts == []
    else:
        assert requisition.status == builders.SENT
        assert len(fakes.mock.posts) == 1


@NOT_BUILT
def test_ac_34_price_per_price_unit_is_used(fakes, clock, client_as):
    """SAP gives 2,000 EUR per 10 PC: 200 per PC, so 60 PC = 12,000 needs approval."""
    fakes.sap.orders.append(one_component_order("1000101", days(1), "RM-1", "100"))
    fakes.sap.stock.append(
        Stock("RM-1", Decimal("0"), price=Decimal("2000"), price_unit=Decimal("10"))
    )
    sync()

    client_as("Planner").post(ABOVE_LIMIT_CREATE, builders.requisition_form("60"))

    assert builders.requisitions()[0].status == builders.AWAITING_APPROVAL
    assert fakes.mock.posts == []


@NOT_BUILT
def test_ac_34_no_price_needs_approval(fakes, clock, client_as):
    fakes.sap.orders.append(one_component_order("1000101", days(1), "RM-1", "100"))
    fakes.sap.stock.append(Stock("RM-1", Decimal("0")))  # no valuation row in SAP
    sync()

    client_as("Planner").post(ABOVE_LIMIT_CREATE, builders.requisition_form("1"))

    assert builders.requisitions()[0].status == builders.AWAITING_APPROVAL
    assert fakes.mock.posts == []


@NOT_BUILT
def test_ac_34_browser_side_panel_shows_awaiting_approval(fakes, running_clock, browser_as):
    from playwright.sync_api import expect

    above_limit_plant(fakes.sap)

    sync()

    page = browser_as("/orders/1000101/", role="Planner")
    page.get_by_role("row").filter(has_text="RM-1").get_by_role("button", name="Request").click()
    page.get_by_label("Quantity", exact=False).fill("60")
    page.get_by_role("button", name="Send requisition").click()

    expect(page.get_by_text("Sent to SAP once a manager approves.")).to_be_visible()
    assert fakes.mock.posts == []
