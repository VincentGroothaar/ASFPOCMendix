"""Unit tests for the unit conversion service (#19, U-1 to U-7). No database, no SAP."""

import decimal
from decimal import Decimal

import pytest

from cockpit.services.units import UnitMismatch, convert

MASS = {"G": "0.001", "KG": "1", "TO": "1000"}
VOLUME = {"ML": "0.001", "L": "1", "M3": "1000"}
LENGTH = {"MM": "0.001", "CM": "0.01", "M": "1"}


def same_dimension_pairs():
    """Every ordered pair of units within one dimension, identity included (27 pairs)."""
    for units in (MASS, VOLUME, LENGTH):
        for from_unit, from_factor in units.items():
            for to_unit, to_factor in units.items():
                yield from_unit, to_unit, Decimal(from_factor) / Decimal(to_factor)


# --- U-1: exact conversion within one dimension -----------------------------------------------


@pytest.mark.parametrize(("from_unit", "to_unit", "ratio"), list(same_dimension_pairs()))
def test_every_pair_within_a_dimension_converts_exactly(from_unit, to_unit, ratio):
    result = convert(Decimal("1.5"), from_unit, to_unit)

    assert isinstance(result, Decimal)
    assert result == Decimal("1.5") * ratio


@pytest.mark.parametrize(
    ("quantity", "from_unit", "to_unit", "expected"),
    [
        ("1500", "G", "KG", "1.5"),
        ("2", "TO", "KG", "2000"),
        ("0.001", "TO", "KG", "1"),
        ("1", "M3", "L", "1000"),
        ("250", "ML", "L", "0.25"),
        ("5", "CM", "MM", "50"),
        ("1", "MM", "M", "0.001"),
    ],
)
def test_known_examples(quantity, from_unit, to_unit, expected):
    assert convert(Decimal(quantity), from_unit, to_unit) == Decimal(expected)


# --- U-2: same unit returns the quantity unchanged ---------------------------------------------


@pytest.mark.parametrize("unit", ["PC", "KG", "EA"])
def test_same_unit_returns_the_quantity_unchanged(unit):
    quantity = Decimal("10.500")

    assert convert(quantity, unit, unit) is quantity


# --- U-3: anything else is a unit mismatch ------------------------------------------------------


@pytest.mark.parametrize(
    ("from_unit", "to_unit"),
    [
        ("PC", "KG"),  # piece against mass
        ("KG", "L"),  # mass against volume
        ("M", "G"),  # length against mass
        ("T", "KG"),  # "T" is not SAP's code for tonne ("TO" is)
        ("KG", "XYZ"),  # unknown code
        ("kg", "G"),  # codes are matched exactly, no lower case
    ],
)
def test_other_unit_differences_are_a_mismatch(from_unit, to_unit):
    with pytest.raises(UnitMismatch) as error:
        convert(Decimal("1"), from_unit, to_unit)

    assert isinstance(error.value, ValueError)
    assert error.value.from_unit == from_unit
    assert error.value.to_unit == to_unit


# --- U-4: only Decimal quantities (INV-5) -------------------------------------------------------


@pytest.mark.parametrize("quantity", [1.5, 2, "2", True])
def test_a_quantity_that_is_not_a_decimal_is_refused(quantity):
    with pytest.raises(TypeError):
        convert(quantity, "KG", "G")


@pytest.mark.parametrize("quantity", ["NaN", "Infinity", "-Infinity"])
def test_a_quantity_that_is_not_finite_is_refused(quantity):
    with pytest.raises(ValueError) as error:
        convert(Decimal(quantity), "KG", "G")

    assert not isinstance(error.value, UnitMismatch)


# --- U-5: no rounding ---------------------------------------------------------------------------


def test_small_results_are_not_rounded():
    assert convert(Decimal("1"), "MM", "M") == Decimal("0.001")
    assert convert(Decimal("0.0001"), "KG", "G") == Decimal("0.1")
    assert convert(Decimal("0.001"), "G", "TO") == Decimal("0.000000001")


# --- U-6: no positive exponent ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("quantity", "from_unit", "to_unit", "text"),
    [
        ("2", "KG", "G", "2000"),
        ("5", "CM", "MM", "50"),
        ("0.5", "KG", "G", "500"),
        ("1500", "G", "KG", "1.500"),
    ],
)
def test_converted_results_have_no_positive_exponent(quantity, from_unit, to_unit, text):
    assert str(convert(Decimal(quantity), from_unit, to_unit)) == text


# --- U-7: exactness is enforced, not assumed ----------------------------------------------------


@pytest.mark.parametrize(
    ("digits", "from_unit", "to_unit"),
    [
        (29, "KG", "G"),  # more digits than the 28 a result may hold
        (28, "TO", "G"),  # the result needs 34 digits
        (23, "TO", "G"),  # the multiplication fits, the step that drops the exponent does not
    ],
)
def test_a_result_that_cannot_be_exact_raises(digits, from_unit, to_unit):
    with pytest.raises(ArithmeticError) as error:
        convert(Decimal("1" * digits), from_unit, to_unit)

    assert not isinstance(error.value, UnitMismatch)


def test_a_long_quantity_to_a_larger_unit_stays_exact():
    assert convert(Decimal("1" * 28), "G", "TO") == Decimal("1111111111111111111111.111111")


def test_the_global_decimal_context_does_not_change_the_result():
    with decimal.localcontext() as context:
        context.prec = 10
        context.traps[decimal.InvalidOperation] = False
        context.traps[decimal.Inexact] = False

        assert convert(Decimal("123456789012.345"), "KG", "G") == Decimal("123456789012345")
        with pytest.raises(ArithmeticError):
            convert(Decimal("1" * 23), "TO", "G")
