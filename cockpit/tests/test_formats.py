"""Formats of dates, quantities and money (ui-spec 6, AC-51, INV-5)."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from cockpit.services.formats import (
    format_date,
    format_datetime,
    format_money,
    format_quantity,
    format_short_date,
)


def test_dates() -> None:
    assert format_date(date(2026, 11, 3)) == "03 Nov 2026"
    assert format_short_date(date(2026, 11, 4)) == "04 Nov"


def test_date_time_is_shown_in_the_app_time_zone() -> None:
    # 09:11 UTC is 10:11 in Europe/Amsterdam (TIME_ZONE) in November.
    assert format_datetime(datetime(2026, 11, 2, 9, 11, tzinfo=UTC)) == "02 Nov 10:11"


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [
        (Decimal("1500"), "G", "1,500 G"),
        (Decimal("1500.000"), "G", "1,500 G"),
        (Decimal("20.000"), "PC", "20 PC"),
        (Decimal("1.500"), "KG", "1.5 KG"),
        (Decimal("1.234567"), "KG", "1.235 KG"),
        (Decimal("0.0005"), "L", "0.001 L"),
        (Decimal("0"), "PC", "0 PC"),
        (Decimal("3200"), "ML", "3,200 ML"),
    ],
)
def test_quantities_drop_trailing_zeros_and_round_above_3_decimals(value, unit, expected) -> None:
    assert format_quantity(value, unit) == expected


def test_quantity_as_sent_to_sap_keeps_3_decimals() -> None:
    assert format_quantity(Decimal("8"), "KG", as_sent=True) == "8.000 KG"
    assert format_quantity(Decimal("1234.5678"), "G", as_sent=True) == "1,234.568 G"


@pytest.mark.parametrize("value", [1.5, 2, "2"])
def test_a_quantity_that_is_not_a_decimal_is_refused(value) -> None:
    with pytest.raises(TypeError):
        format_quantity(value, "KG")


def test_money_has_2_decimals_rounded_half_up() -> None:
    assert format_money(Decimal("1250"), "EUR") == "1,250.00 EUR"
    assert format_money(Decimal("12400.005"), "USD") == "12,400.01 USD"
    with pytest.raises(TypeError):
        format_money(1250.0, "EUR")


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_a_quantity_that_is_not_a_finite_number_is_refused(value) -> None:
    with pytest.raises(ValueError):
        format_quantity(value, "PC")


def test_a_tiny_negative_shows_as_zero_not_minus_zero() -> None:
    assert format_quantity(Decimal("-0.0004"), "PC") == "0 PC"
    assert format_quantity(Decimal("-0.0004"), "PC", as_sent=True) == "0.000 PC"
    assert format_money(Decimal("-0.001"), "EUR") == "0.00 EUR"


@pytest.mark.parametrize("unit", [None, "", "  "])
def test_a_missing_unit_or_currency_is_refused(unit) -> None:
    with pytest.raises(ValueError):
        format_quantity(Decimal("1"), unit)
    with pytest.raises(ValueError):
        format_money(Decimal("1"), unit)


def test_a_date_and_time_is_shown_as_its_date_in_the_app_time_zone() -> None:
    # 23:30 UTC on 2 Nov is already 3 Nov in Europe/Amsterdam.
    late = datetime(2026, 11, 2, 23, 30, tzinfo=UTC)

    assert format_date(late) == "03 Nov 2026"
    assert format_short_date(late) == "03 Nov"
