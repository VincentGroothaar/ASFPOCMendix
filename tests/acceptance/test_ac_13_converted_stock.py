"""AC-13 (REQ-3): stock in a different unit of the same dimension is shown converted, with the
original in the tooltip. Unit tests on `units.convert` plus a browser check
(1,500 G shown as 1.5 KG)."""

from decimal import Decimal

import pytest

from tests.acceptance.support import Stock, days, one_component_order, sync


@pytest.mark.parametrize(
    ("quantity", "from_unit", "to_unit", "expected"),
    [
        ("1500", "G", "KG", "1.5"),
        ("2", "TO", "KG", "2000"),
        ("250", "ML", "L", "0.25"),
        ("1", "M3", "L", "1000"),
        ("5", "CM", "MM", "50"),
        ("1500", "MM", "M", "1.5"),
        ("7", "KG", "KG", "7"),
    ],
)
def test_ac_13_convert_within_one_dimension(quantity, from_unit, to_unit, expected):
    from cockpit.services.units import convert

    result = convert(Decimal(quantity), from_unit, to_unit)

    assert isinstance(result, Decimal)
    assert result == Decimal(expected)


@pytest.mark.parametrize(("from_unit", "to_unit"), [("PC", "KG"), ("KG", "L"), ("M", "G")])
def test_ac_13_convert_across_dimensions_is_a_mismatch(from_unit, to_unit):
    from cockpit.services.units import UnitMismatch, convert

    with pytest.raises(UnitMismatch):
        convert(Decimal("1"), from_unit, to_unit)


def test_ac_13_browser_converted_stock_shows_the_original_on_hover(
    fakes, running_clock, browser_as
):
    from playwright.sync_api import expect

    fakes.sap.orders.append(one_component_order("1000101", days(1), "RM-1", "1", unit="KG"))
    fakes.sap.stock.append(Stock("RM-1", Decimal("1500"), unit="G"))

    sync()

    page = browser_as("/orders/1000101/", role="Viewer")
    available = page.get_by_text("1.5 KG", exact=True).first
    expect(available).to_be_visible()
    available.hover()

    original = "1,500 G (= 1.5 KG)"
    title = available.get_attribute("title") or ""
    if original not in title:
        expect(page.get_by_text(original)).to_be_visible()
