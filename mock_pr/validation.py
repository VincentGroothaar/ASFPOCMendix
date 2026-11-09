"""Check a purchase requisition the way SAP does before it is stored.

Two kinds of check:

1. Every field sent must exist in SAP's $metadata and have the right type and length.
2. A short list of fields must be filled in (REQUIRED_HEADER_FIELDS, REQUIRED_ITEM_FIELDS).
   SAP's metadata marks almost nothing as required, but SAP rejects a requisition without
   these. The list is documented in mock_pr/README.md.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from mock_pr.metadata import EntityType, Property

ITEMS_NAVIGATION = "to_PurchaseReqnItem"

REQUIRED_HEADER_FIELDS = ["PurchaseRequisitionType"]
REQUIRED_ITEM_FIELDS = [
    "Material",
    "Plant",
    "RequestedQuantity",
    "BaseUnit",
    "DeliveryDate",
    "PurchasingGroup",
]

# OData V2 sends dates as "/Date(<milliseconds since 1970 UTC>)/", optionally with an offset.
ODATA_DATE = re.compile(r"^/Date\((-?\d+)([+-]\d{4})?\)/$")
# OData V2 sends decimals as plain text: digits, optionally a point and more digits.
PLAIN_DECIMAL = re.compile(r"^-?\d+(\.\d+)?$")
# Characters Postgres cannot store in text: NUL and unpaired UTF-16 surrogates.
UNSTORABLE_CHARACTERS = re.compile("[\x00\ud800-\udfff]")
INT32_RANGE = range(-(2**31), 2**31)
# Item numbers go 10, 20, ... and PurchaseRequisitionItem holds at most 5 characters.
MAX_ITEMS = 9999


class InvalidRequisition(Exception):
    """The request body is not a valid purchase requisition. The message is shown to the client."""


@dataclass
class Requisition:
    """A checked requisition: header fields, and the fields of each item."""

    header: dict
    items: list[dict]


def validate_requisition(
    body: object, header_type: EntityType, item_type: EntityType
) -> Requisition:
    """Check a deep-insert body (header with `to_PurchaseReqnItem`) and return its fields.

    Raises InvalidRequisition with an SAP-like message for the first problem found.
    Dates come back in OData form ("/Date(...)/"); other values come back as sent.
    """
    if not isinstance(body, dict):
        raise InvalidRequisition("The request body must be a JSON object.")

    header_fields = {key: value for key, value in body.items() if key != ITEMS_NAVIGATION}
    header = _check_fields(header_fields, header_type, "header")
    _check_required(header, REQUIRED_HEADER_FIELDS, "header")

    items = []
    for number, item_fields in enumerate(_item_list(body.get(ITEMS_NAVIGATION)), start=1):
        where = f"item {number}"
        if not isinstance(item_fields, dict):
            raise InvalidRequisition(f"Each entry in {ITEMS_NAVIGATION} must be a JSON object.")
        item = _check_fields(item_fields, item_type, where)
        _check_required(item, REQUIRED_ITEM_FIELDS, where)
        if Decimal(item["RequestedQuantity"]) <= 0:
            raise InvalidRequisition(f"RequestedQuantity in {where} must be greater than 0.")
        items.append(item)

    return Requisition(header=header, items=items)


def _item_list(value: object) -> list:
    """Return the items of a deep insert. OData V2 allows a plain list or {"results": [...]}."""
    if isinstance(value, dict) and set(value) == {"results"}:
        value = value["results"]
    if not isinstance(value, list) or not value:
        raise InvalidRequisition(f"A requisition needs at least one item in {ITEMS_NAVIGATION}.")
    if len(value) > MAX_ITEMS:
        raise InvalidRequisition(f"A requisition can have at most {MAX_ITEMS} items.")
    return value


def _check_fields(fields: dict, entity_type: EntityType, where: str) -> dict:
    """Check every field against the entity type and return the checked values."""
    checked = {}
    for name, value in fields.items():
        if name == "__metadata":
            continue
        if name in entity_type.navigation:
            raise InvalidRequisition(f"The mock does not support a deep insert of '{name}'.")
        prop = entity_type.properties.get(name)
        if prop is None:
            raise InvalidRequisition(f"Property '{name}' is invalid ({where}).")
        checked[name] = check_value(prop, value, where)
    return checked


def _check_required(fields: dict, required: list[str], where: str) -> None:
    """Raise InvalidRequisition if a required field is missing or empty."""
    for name in required:
        if fields.get(name) in (None, ""):
            raise InvalidRequisition(f"Property '{name}' is required ({where}).")


def check_value(prop: Property, value: object, where: str) -> object:
    """Check one value against its $metadata type and return it (dates in OData form)."""
    problem = f"Property '{prop.name}' has an invalid value ({where})"
    if value is None:
        if not prop.nullable:
            raise InvalidRequisition(f"Property '{prop.name}' must not be null ({where}).")
        return None

    match prop.edm_type:
        case "Edm.String":
            if not isinstance(value, str):
                raise InvalidRequisition(f"{problem}: expected text.")
            if UNSTORABLE_CHARACTERS.search(value):
                raise InvalidRequisition(f"{problem}: contains a character that is not allowed.")
            if prop.max_length is not None and len(value) > prop.max_length:
                raise InvalidRequisition(f"{problem}: at most {prop.max_length} characters.")
            return value
        case "Edm.Boolean":
            if not isinstance(value, bool):
                raise InvalidRequisition(f"{problem}: expected true or false.")
            return value
        case "Edm.Decimal":
            _check_decimal(prop, value, problem)
            return value
        case "Edm.Int32":
            if isinstance(value, bool) or not isinstance(value, int) or value not in INT32_RANGE:
                raise InvalidRequisition(f"{problem}: expected a whole number.")
            return value
        case "Edm.DateTime" | "Edm.DateTimeOffset":
            return _odata_date(value, problem)
        case _:
            raise InvalidRequisition(f"{problem}: type {prop.edm_type} is not supported.")


def _check_decimal(prop: Property, value: object, problem: str) -> None:
    """Check a decimal sent as a string (the OData V2 rule) or a whole number."""
    if isinstance(value, bool) or not isinstance(value, str | int):
        raise InvalidRequisition(f'{problem}: expected a number as text, e.g. "10.5".')
    text = str(value)
    if not PLAIN_DECIMAL.match(text):
        raise InvalidRequisition(f'{problem}: not a number. Use digits and a point, e.g. "10.5".')

    scale = prop.scale or 0
    whole_part, _, decimal_part = text.removeprefix("-").partition(".")
    whole_digits = len(whole_part.lstrip("0"))
    decimals = len(decimal_part)
    if decimals > scale:
        raise InvalidRequisition(f"{problem}: at most {scale} decimals.")
    if prop.precision is not None and whole_digits > prop.precision - scale:
        raise InvalidRequisition(
            f"{problem}: at most {prop.precision - scale} digits before the decimal point."
        )


def _odata_date(value: object, problem: str) -> str:
    """Accept "/Date(ms)/" or an ISO date-time and return the OData form "/Date(ms)/"."""
    if not isinstance(value, str):
        raise InvalidRequisition(f"{problem}: expected a date.")
    odata_match = ODATA_DATE.match(value)
    if odata_match:
        milliseconds = int(odata_match.group(1))
        try:
            datetime.fromtimestamp(milliseconds / 1000, UTC)
        except (OverflowError, ValueError, OSError):
            raise InvalidRequisition(f"{problem}: the date is out of range.") from None
        return value
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        raise InvalidRequisition(
            f'{problem}: expected a date such as "/Date(1762646400000)/" or "2026-11-09T00:00:00".'
        ) from None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return f"/Date({int(moment.timestamp() * 1000)})/"
