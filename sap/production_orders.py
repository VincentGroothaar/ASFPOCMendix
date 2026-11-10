"""Released open production orders and their components (API_PRODUCTION_ORDER_2_SRV).

Field names, the release filter and the start-date field come from the sandbox data check,
docs/sandbox/findings.md (#7), as frozen in spec.md "SAP reads".
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sap.client import (
    ODataClient,
    SapDataError,
    check_plant,
    parse_date,
    parse_decimal,
    parse_text,
    quote,
)

SERVICE = "API_PRODUCTION_ORDER_2_SRV"
ENTITY_SET = "A_ProductionOrder_2"
COMPONENTS = "to_ProductionOrderComponent"

# Released, and not delivered, technically completed, closed, deleted or marked for deletion.
# OrderIsReleased stays 'X' after delivery, so the other flags are needed too (findings #7).
RELEASED_OPEN_FILTER = (
    "OrderIsReleased eq 'X' and OrderIsDelivered eq '' and OrderIsTechnicallyCompleted eq '' "
    "and OrderIsClosed eq '' and OrderIsDeleted eq '' and OrderIsMarkedForDeletion eq ''"
)

ORDER_FIELDS = [
    "ManufacturingOrder",
    "ProductionPlant",
    "Material",
    "TotalQuantity",
    "ProductionUnit",
    "MfgOrderScheduledStartDate",
    "MfgOrderPlannedStartDate",
]
COMPONENT_FIELDS = [
    "ReservationItem",
    "Material",
    "RequiredQuantity",
    "WithdrawnQuantity",
    "BaseUnit",
]


@dataclass(frozen=True)
class Component:
    """One component line of a production order. Quantities are in `unit`."""

    item: str
    material: str
    required_quantity: Decimal
    withdrawn_quantity: Decimal
    unit: str


@dataclass(frozen=True)
class ProductionOrder:
    """A released open production order with its components, as SAP returns it."""

    number: str
    plant: str
    material: str
    quantity: Decimal
    unit: str
    start_date: date
    components: tuple[Component, ...]


def read_released_orders(client: ODataClient, plant: str) -> list[ProductionOrder]:
    """Read all released open orders of one plant, with their components (REQ-1, REQ-2).

    One call with $expand, plus more pages only if the plant has more orders than one page.
    Components are sorted by item number (as a number), the order in which they take
    stock. Raises SapUnavailable when SAP fails and SapDataError when its data is unusable.
    """
    check_plant(plant)
    select = ORDER_FIELDS + [f"{COMPONENTS}/{field}" for field in COMPONENT_FIELDS]
    rows = client.get_all(
        SERVICE,
        ENTITY_SET,
        filter=f"ProductionPlant eq {quote(plant)} and {RELEASED_OPEN_FILTER}",
        expand=COMPONENTS,
        select=",".join(select),
        orderby="ManufacturingOrder",
    )
    return [_order_from_row(row) for row in rows]


def _order_from_row(row: dict) -> ProductionOrder:
    """Map one SAP order row (with expanded components) to a ProductionOrder."""
    number = parse_text(row, "ManufacturingOrder")
    # The scheduled start is the date production is planned to begin. Fall back to the basic
    # (planned) start if it is ever empty; in the sandbox both are always filled.
    start_date = parse_date(row.get("MfgOrderScheduledStartDate")) or parse_date(
        row.get("MfgOrderPlannedStartDate")
    )
    if start_date is None:
        raise SapDataError(f"Production order {number} has no start date in SAP.")

    lines = row.get(COMPONENTS)
    if not isinstance(lines, dict) or not isinstance(lines.get("results"), list):
        raise SapDataError(f"SAP sent production order {number} without its component list.")
    components = [_component_from_row(line) for line in lines["results"]]
    return ProductionOrder(
        number=number,
        plant=parse_text(row, "ProductionPlant"),
        material=parse_text(row, "Material"),
        quantity=parse_decimal(row.get("TotalQuantity"), "TotalQuantity"),
        unit=parse_text(row, "ProductionUnit"),
        start_date=start_date,
        components=tuple(sorted(components, key=_item_number)),
    )


def _component_from_row(row: object) -> Component:
    """Map one SAP component row to a Component."""
    if not isinstance(row, dict):
        raise SapDataError("SAP sent a component that is not an object.")
    return Component(
        item=parse_text(row, "ReservationItem"),
        material=parse_text(row, "Material"),
        required_quantity=parse_decimal(row.get("RequiredQuantity"), "RequiredQuantity"),
        withdrawn_quantity=parse_decimal(row.get("WithdrawnQuantity"), "WithdrawnQuantity"),
        unit=parse_text(row, "BaseUnit"),
    )


def _item_number(component: Component) -> int:
    """The item number as a number, so item 10 comes after item 9 ("10" < "9" as text)."""
    if not component.item.isdigit():
        raise SapDataError(f"SAP sent component item {component.item!r}, which is not a number.")
    return int(component.item)
