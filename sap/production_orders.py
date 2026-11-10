"""Released open production orders and their components (API_PRODUCTION_ORDER_2_SRV).

Field names, the release filter and the start-date field come from the sandbox data check,
docs/sandbox/findings.md (#7), as frozen in spec.md "SAP reads".
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sap.client import ODataClient, SapDataError, parse_date, parse_decimal, quote

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
    Components are sorted by item number, the order in which they take stock.
    """
    select = ORDER_FIELDS + [f"{COMPONENTS}/{field}" for field in COMPONENT_FIELDS]
    rows = client.get_all(
        SERVICE,
        ENTITY_SET,
        filter=f"ProductionPlant eq {quote(plant)} and {RELEASED_OPEN_FILTER}",
        expand=COMPONENTS,
        select=",".join(select),
        orderby="ManufacturingOrder",
    )
    try:
        return [_order_from_row(row) for row in rows]
    except KeyError as missing:
        raise SapDataError(f"SAP left out field {missing} in a production order.") from None


def _order_from_row(row: dict) -> ProductionOrder:
    """Map one SAP order row (with expanded components) to a ProductionOrder."""
    number = row["ManufacturingOrder"]
    # The scheduled start is the date production is planned to begin. Fall back to the basic
    # (planned) start if it is ever empty; in the sandbox both are always filled.
    start_date = parse_date(row.get("MfgOrderScheduledStartDate")) or parse_date(
        row.get("MfgOrderPlannedStartDate")
    )
    if start_date is None:
        raise SapDataError(f"Production order {number} has no start date in SAP.")

    lines = row.get(COMPONENTS, {}).get("results", [])
    components = sorted((_component_from_row(line) for line in lines), key=lambda c: c.item)
    return ProductionOrder(
        number=number,
        plant=row["ProductionPlant"],
        material=row["Material"],
        quantity=parse_decimal(row["TotalQuantity"], "TotalQuantity"),
        unit=row["ProductionUnit"],
        start_date=start_date,
        components=tuple(components),
    )


def _component_from_row(row: dict) -> Component:
    """Map one SAP component row to a Component."""
    return Component(
        item=row["ReservationItem"],
        material=row["Material"],
        required_quantity=parse_decimal(row["RequiredQuantity"], "RequiredQuantity"),
        withdrawn_quantity=parse_decimal(row["WithdrawnQuantity"], "WithdrawnQuantity"),
        unit=row["BaseUnit"],
    )
