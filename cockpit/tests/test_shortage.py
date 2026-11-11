"""Unit tests for the shortage calculation (#20). Constructed inputs; no database, no SAP.

The acceptance tests (AC-11, AC-14..17, AC-19, INV-5) live in tests/acceptance. These tests
cover INV-6 and the edge cases in the issue's Acceptance table.
"""

from datetime import date
from decimal import Decimal

import pytest

from cockpit.services.shortage import (
    ComponentLine,
    OrderLine,
    ShortageSettings,
    Status,
    StockLine,
    calculate,
)

TODAY = date(2026, 11, 3)
DEFAULT = ShortageSettings()


def line(material: str, required: str, unit: str = "PC", item: str = "1", withdrawn: str = "0"):
    """A component line with Decimal quantities."""
    return ComponentLine(item, material, Decimal(required), Decimal(withdrawn), unit)


def order(number: str, start: date, *lines: ComponentLine) -> OrderLine:
    """An order with the given lines."""
    return OrderLine(number, start, tuple(lines))


def stock(material: str, quantity: str, unit: str = "PC") -> StockLine:
    """A stock line with a Decimal quantity."""
    return StockLine(material, Decimal(quantity), unit)


def one_line_result(required: str, available: str, settings: ShortageSettings = DEFAULT):
    """The result of a single PC line against a single stock line."""
    result = calculate(
        [order("1", TODAY, line("RM", required))], [stock("RM", available)], settings, TODAY
    )
    return result.component("1", "1")


# --- INV-6: later orders never change earlier results ------------------------------------------


def test_inv_6_adding_later_orders_changes_no_earlier_result():
    earlier = [
        order("A", date(2026, 11, 3), line("RM", "60")),
        order("B", date(2026, 11, 4), line("RM", "30"), line("RM-2", "5", item="2")),
    ]
    later = [
        order("C", date(2026, 11, 5), line("RM", "500")),
        order("0", date(2026, 11, 9), line("RM-2", "100")),
    ]
    stocks = [stock("RM", "100"), stock("RM-2", "5")]

    alone = calculate(earlier, stocks, DEFAULT, TODAY)
    with_later = calculate(later + earlier, stocks, DEFAULT, TODAY)

    for number in ("A", "B"):
        assert with_later.orders[number] == alone.orders[number]


# --- Buffer from settings ----------------------------------------------------------------------


def test_buffer_zero_makes_exact_cover_covered():
    assert one_line_result("100", "100", ShortageSettings(Decimal("0"))).status == Status.COVERED


@pytest.mark.parametrize(("available", "status"), [("112.4", "low"), ("112.5", "covered")])
def test_buffer_twelve_and_a_half_percent(available, status):
    expected = {"low": Status.LOW_COVER, "covered": Status.COVERED}[status]
    settings = ShortageSettings(Decimal("12.5"))

    assert one_line_result("100", available, settings).status == expected


def test_result_reports_the_buffer_used():
    result = calculate([], [], ShortageSettings(Decimal("12.5")), TODAY)

    assert result.buffer_percent == Decimal("12.5")


# --- Issued and missing stock ------------------------------------------------------------------


def test_withdrawn_more_than_required_is_issued_with_open_requirement_zero():
    result = calculate(
        [order("1", TODAY, line("RM", "5", withdrawn="7"))], [stock("RM", "10")], DEFAULT, TODAY
    )

    component = result.component("1", "1")
    assert component.status == Status.ISSUED
    assert component.open_requirement == Decimal("0")
    assert (component.available, component.shortage) == (None, None)


def test_issued_line_takes_no_stock():
    orders = [
        order("1", TODAY, line("RM", "5", item="1", withdrawn="5"), line("RM", "10", item="2"))
    ]

    result = calculate(orders, [stock("RM", "10")], DEFAULT, TODAY)

    assert result.component("1", "2").available == Decimal("10")


def test_missing_stock_row_is_short_with_available_zero():
    result = calculate([order("1", TODAY, line("RM", "4"))], [], DEFAULT, TODAY)

    component = result.component("1", "1")
    assert component.status == Status.SHORT
    assert (component.available, component.shortage) == (Decimal("0"), Decimal("4"))


def test_missing_stock_row_takes_the_unit_of_the_first_line():
    orders = [order("1", TODAY, line("RM", "2", "KG", item="1"), line("RM", "500", "G", item="2"))]

    result = calculate(orders, [], DEFAULT, TODAY)

    first, second = result.component("1", "1"), result.component("1", "2")
    assert (first.stock_unit, second.stock_unit) == ("KG", "KG")
    assert second.status == Status.SHORT
    assert second.shortage == Decimal("500")
    assert second.shortage_in_stock_unit == Decimal("0.5")


def test_missing_stock_row_pieces_after_kilograms_is_a_mismatch():
    orders = [order("1", TODAY, line("RM", "2", "KG", item="1"), line("RM", "3", "PC", item="2"))]

    result = calculate(orders, [], DEFAULT, TODAY)

    assert result.component("1", "2").status == Status.UNIT_MISMATCH
    assert result.component("1", "2").stock_unit == "KG"


def test_issued_line_does_not_set_the_unit_of_a_missing_stock_row():
    orders = [
        order(
            "1",
            TODAY,
            line("RM", "3", "PC", item="1", withdrawn="3"),
            line("RM", "2", "KG", item="2"),
        )
    ]

    result = calculate(orders, [], DEFAULT, TODAY)

    issued, open_line = result.component("1", "1"), result.component("1", "2")
    assert (issued.status, issued.stock_unit) == (Status.ISSUED, "PC")
    assert (open_line.status, open_line.available) == (Status.SHORT, Decimal("0"))
    assert open_line.stock_unit == "KG"


# --- Ordering and input checks -----------------------------------------------------------------


def test_item_numbers_sort_as_integers():
    # Item 10 is listed first; as text "10" < "9", but item 9 must take the stock.
    orders = [order("1", TODAY, line("RM", "8", item="10"), line("RM", "8", item="9"))]

    result = calculate(orders, [stock("RM", "10")], DEFAULT, TODAY)

    assert result.component("1", "9").available == Decimal("10")
    assert result.component("1", "10").available == Decimal("2")
    assert [c.item for c in result.orders["1"].components] == ["9", "10"]


def test_item_number_that_is_not_a_whole_number_raises():
    with pytest.raises(ValueError, match="item"):
        calculate([order("1", TODAY, line("RM", "1", item="1a"))], [], DEFAULT, TODAY)


def test_duplicate_stock_rows_raise():
    with pytest.raises(ValueError, match="stock line"):
        calculate([], [stock("RM", "1"), stock("RM", "2")], DEFAULT, TODAY)


def test_duplicate_order_numbers_raise():
    with pytest.raises(ValueError, match="order number"):
        calculate([order("1", TODAY), order("1", TODAY)], [], DEFAULT, TODAY)


def test_second_line_of_a_material_sees_the_remainder():
    orders = [order("1", TODAY, line("RM", "60", item="1"), line("RM", "60", item="2"))]

    result = calculate(orders, [stock("RM", "100")], DEFAULT, TODAY)

    second = result.component("1", "2")
    assert (second.status, second.available, second.shortage) == (
        Status.SHORT,
        Decimal("40"),
        Decimal("20"),
    )


def test_balance_is_never_reported_below_zero():
    orders = [order("A", TODAY, line("RM", "150")), order("B", date(2026, 11, 4), line("RM", "10"))]

    result = calculate(orders, [stock("RM", "100")], DEFAULT, TODAY)

    later = result.component("B", "1")
    assert (later.available, later.shortage) == (Decimal("0"), Decimal("10"))


# --- Order rollup ------------------------------------------------------------------------------


def test_order_with_only_issued_and_mismatch_lines_has_no_status():
    orders = [
        order(
            "1",
            TODAY,
            line("RM", "5", item="1", withdrawn="5"),
            line("RM-KG", "1", "PC", item="2"),
        )
    ]

    result = calculate(orders, [stock("RM-KG", "10", "KG")], DEFAULT, TODAY)

    assert result.orders["1"].status is None
    assert result.orders["1"].unit_mismatch is True


@pytest.mark.parametrize(
    ("start", "overdue"),
    [(date(2026, 11, 2), True), (date(2026, 11, 3), False), (date(2026, 11, 4), False)],
)
def test_overdue_only_when_start_is_before_today(start, overdue):
    result = calculate([order("1", start)], [], DEFAULT, TODAY)

    assert result.orders["1"].overdue is overdue


def test_orders_are_returned_in_allocation_order():
    orders = [
        order("2", date(2026, 11, 3)),
        order("1", date(2026, 11, 4)),
        order("0", date(2026, 11, 3)),
    ]

    result = calculate(orders, [], DEFAULT, TODAY)

    assert list(result.orders) == ["0", "2", "1"]


# --- Stock-unit values -------------------------------------------------------------------------


def test_shortage_and_available_in_the_stock_unit():
    result = calculate(
        [order("1", TODAY, line("RM", "2", "KG"))], [stock("RM", "1500", "G")], DEFAULT, TODAY
    )

    component = result.component("1", "1")
    assert component.stock_unit == "G"
    assert component.available_in_stock_unit == Decimal("1500")
    assert component.shortage_in_stock_unit == Decimal("500")
    assert (component.available, component.shortage) == (Decimal("1.5"), Decimal("0.5"))


def test_unknown_item_raises_key_error():
    result = calculate([order("1", TODAY, line("RM", "1"))], [], DEFAULT, TODAY)

    with pytest.raises(KeyError):
        result.component("1", "2")
