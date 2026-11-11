"""How dates, quantities and money are shown on every screen (ui-spec section 6).

Plain functions, so every screen formats the same way. The template filters in
`cockpit/templatetags/ui.py` call these.
"""

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

# Quantities are shown with at most 3 decimals (ui-spec 6, REQ-5).
QUANTITY_DECIMALS = Decimal("0.001")
MONEY_DECIMALS = Decimal("0.01")


def format_date(value: date) -> str:
    """A date in tables and headers: `03 Nov 2026`."""
    return value.strftime("%d %b %Y")


def format_short_date(value: date) -> str:
    """A date in compact columns (Needed by, First needed, dashboard): `04 Nov`."""
    return value.strftime("%d %b")


def format_datetime(value: datetime) -> str:
    """A date and time in the app's time zone: `02 Nov 10:11`."""
    if timezone.is_aware(value):
        value = timezone.localtime(value)
    return value.strftime("%d %b %H:%M")


def format_quantity(value: Decimal, unit: str, as_sent: bool = False) -> str:
    """A quantity with its unit: `1,500 G`, `20 PC`, `1.235 KG`.

    More than 3 decimals are rounded half-up to 3, for display only. Trailing zeros are
    dropped (a stored `20.000` shows `20 PC`), except with `as_sent=True`, which always shows
    exactly 3 decimals, the way the quantity is sent to SAP (`8.000 KG`). Only `Decimal` is
    accepted, never float (INV-5).
    """
    _require_decimal(value)
    rounded = value.quantize(QUANTITY_DECIMALS, rounding=ROUND_HALF_UP)
    if as_sent:
        number = f"{rounded:,.3f}"
    else:
        number = _without_trailing_zeros(rounded)
    return f"{number} {unit}"


def format_money(value: Decimal, currency: str) -> str:
    """An amount with the plant's currency code: `1,250.00 EUR` (2 decimals, half-up)."""
    _require_decimal(value)
    rounded = value.quantize(MONEY_DECIMALS, rounding=ROUND_HALF_UP)
    return f"{rounded:,.2f} {currency}"


def _without_trailing_zeros(value: Decimal) -> str:
    """`1500.000` -> `1,500`, `1.500` -> `1.5`, with a thousands comma."""
    text = f"{value:,f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _require_decimal(value: object) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"Expected a Decimal, got {type(value).__name__} (INV-5)")
