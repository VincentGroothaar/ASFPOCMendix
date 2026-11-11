"""Exact unit conversion between SAP unit codes (REQ-3, REQ-4, INV-5).

Only units of the same dimension convert: mass, volume and length. Anything
else is a unit mismatch, which the cockpit shows as a grey status. Codes are
SAP's commercial codes exactly as the sandbox returns them (e.g. "TO" for
tonne, "PC" for piece); there are no aliases.
"""

from decimal import (
    Decimal,
    DivisionByZero,
    Inexact,
    InvalidOperation,
    Overflow,
    Rounded,
    localcontext,
)

# Each unit code maps to (dimension, exact factor to the dimension's base unit).
UNIT_FACTORS: dict[str, tuple[str, Decimal]] = {
    "G": ("mass", Decimal("0.001")),
    "KG": ("mass", Decimal("1")),
    "TO": ("mass", Decimal("1000")),
    "ML": ("volume", Decimal("0.001")),
    "L": ("volume", Decimal("1")),
    "M3": ("volume", Decimal("1000")),
    "MM": ("length", Decimal("0.001")),
    "CM": ("length", Decimal("0.01")),
    "M": ("length", Decimal("1")),
}

# With these traps a result that is not exact raises an ArithmeticError
# instead of being rounded silently.
_PRECISION = 28
_EXACT_TRAPS = [InvalidOperation, DivisionByZero, Overflow, Inexact, Rounded]


class UnitMismatch(ValueError):
    """Two units that cannot be converted into each other."""

    def __init__(self, from_unit: str, to_unit: str) -> None:
        super().__init__(f"Cannot convert {from_unit} to {to_unit}")
        self.from_unit = from_unit
        self.to_unit = to_unit


def convert(quantity: Decimal, from_unit: str, to_unit: str) -> Decimal:
    """Convert a quantity from one unit to another of the same dimension.

    Returns the exact result, never rounded. A converted result never has a
    positive exponent, so 2 KG to G is Decimal("2000"), not Decimal("2E+3").

    Raises:
        TypeError: the quantity is not a Decimal (INV-5).
        ValueError: the quantity is NaN or infinite.
        UnitMismatch: the units differ and are not of the same dimension.
        ArithmeticError: the result cannot be held exactly in 28 digits.
    """
    if not isinstance(quantity, Decimal):
        raise TypeError(f"quantity must be a Decimal, not {type(quantity).__name__}")
    if not quantity.is_finite():
        raise ValueError(f"quantity must be a finite number, not {quantity}")

    if from_unit == to_unit:
        return quantity

    if from_unit not in UNIT_FACTORS or to_unit not in UNIT_FACTORS:
        raise UnitMismatch(from_unit, to_unit)
    from_dimension, from_factor = UNIT_FACTORS[from_unit]
    to_dimension, to_factor = UNIT_FACTORS[to_unit]
    if from_dimension != to_dimension:
        raise UnitMismatch(from_unit, to_unit)

    with localcontext(prec=_PRECISION, traps=_EXACT_TRAPS):
        result = quantity * from_factor / to_factor
        if result.as_tuple().exponent > 0:
            result = result.quantize(Decimal(1))
    return result
