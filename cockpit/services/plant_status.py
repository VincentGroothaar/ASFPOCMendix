"""The statuses of one plant, calculated from its stored snapshot (#27, shared).

Reads the snapshot that the sync (#24) wrote, maps it into the plain input types of
`shortage.calculate` (#20) and calculates with the current cover buffer. The order list, the
order detail, requisitions and the dashboard all use this, so every screen shows the same
statuses (INV-6). Read only.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from cockpit.models import Component, ProductionOrder, Stock
from cockpit.services.buffer import current_buffer
from cockpit.services.shortage import (
    ComponentLine,
    ComponentResult,
    OrderLine,
    PlantResult,
    ShortageSettings,
    Status,
    StockLine,
    calculate,
)


def plant_result(plant: str, today: date) -> PlantResult:
    """Calculate the statuses of all active orders of a plant from its snapshot.

    All active orders are passed, whatever date range a screen shows, because an order's
    status depends on the orders that start before it (INV-6).
    """
    orders = ProductionOrder.objects.filter(plant=plant, is_active=True).prefetch_related(
        "components"
    )
    order_lines = [
        OrderLine(
            number=order.number,
            start_date=order.start_date,
            components=tuple(
                ComponentLine(
                    item=component.item,
                    material=component.material,
                    required=component.required_quantity,
                    withdrawn=component.withdrawn_quantity,
                    unit=component.unit,
                )
                for component in order.components.all()
            ),
        )
        for order in orders
    ]
    stock_lines = [
        StockLine(material=row.material, quantity=row.quantity, unit=row.unit)
        for row in Stock.objects.filter(plant=plant)
    ]
    settings = ShortageSettings(buffer_percent=current_buffer())
    return calculate(order_lines, stock_lines, settings, today)


# --- Order detail (REQ-2 to REQ-4, issue #26) ---------------------------------------------------


@dataclass(frozen=True)
class DetailRow:
    """One component line on the order detail page.

    Quantities are in the order unit (`unit`). `status`, `available` and `shortage` are None
    when the line is not checked: Issued and Unit mismatch lines have no available or shortage,
    and an inactive order has no status at all.
    """

    item: str
    material: str
    description: str
    open_requirement: Decimal
    unit: str
    status: Status | None
    available: Decimal | None
    shortage: Decimal | None
    stock_unit: str
    available_in_stock_unit: Decimal | None

    @property
    def converted(self) -> bool:
        """True when the stock is in another unit and was converted for `available`."""
        return self.available is not None and self.stock_unit != self.unit


@dataclass(frozen=True)
class OrderDetail:
    """Everything the order detail page shows about one order."""

    number: str
    plant: str
    material: str
    description: str
    quantity: Decimal
    unit: str
    start_date: date
    is_active: bool
    status: Status | None  # None: no line counts, or the order is inactive
    overdue: bool
    unit_mismatch: bool
    buffer_percent: Decimal
    rows: tuple[DetailRow, ...]  # in item order


def order_detail(number: str, today: date) -> OrderDetail | None:
    """The order with its components, stock and statuses, or None when it is not stored.

    An active order gets its statuses from the whole plant (`plant_result`), so they match the
    order list (INV-6). An inactive order (no longer released in SAP) is not calculated: it
    shows its last synced lines with the open requirement only (decision 2 on #26).
    """
    order = ProductionOrder.objects.filter(number=number).first()
    if order is None:
        return None
    components = sorted(order.components.all(), key=lambda line: _item_number(line.item))
    if not order.is_active:
        return _detail(
            order,
            status=None,
            overdue=False,
            unit_mismatch=False,
            buffer_percent=current_buffer(),
            rows=tuple(_unchecked_row(line) for line in components),
        )

    result = plant_result(order.plant, today)
    calculated = result.orders[order.number]
    descriptions = {line.item: line.description for line in components}
    rows = tuple(_checked_row(line, descriptions[line.item]) for line in calculated.components)
    return _detail(
        order,
        status=calculated.status,
        overdue=calculated.overdue,
        unit_mismatch=calculated.unit_mismatch,
        buffer_percent=result.buffer_percent,
        rows=rows,
    )


def _detail(order: ProductionOrder, **calculated: object) -> OrderDetail:
    """The header fields of the stored order plus what was calculated."""
    return OrderDetail(
        number=order.number,
        plant=order.plant,
        material=order.material,
        description=order.description,
        quantity=order.quantity,
        unit=order.unit,
        start_date=order.start_date,
        is_active=order.is_active,
        **calculated,
    )


def _checked_row(result: ComponentResult, description: str) -> DetailRow:
    """A line of an active order, from its calculated result."""
    return DetailRow(
        item=result.item,
        material=result.material,
        description=description,
        open_requirement=result.open_requirement,
        unit=result.unit,
        status=result.status,
        available=result.available,
        shortage=result.shortage,
        stock_unit=result.stock_unit,
        available_in_stock_unit=result.available_in_stock_unit,
    )


def _unchecked_row(line: Component) -> DetailRow:
    """A line of an inactive order: only the open requirement, no status."""
    return DetailRow(
        item=line.item,
        material=line.material,
        description=line.description,
        open_requirement=max(Decimal("0"), line.required_quantity - line.withdrawn_quantity),
        unit=line.unit,
        status=None,
        available=None,
        shortage=None,
        stock_unit=line.unit,
        available_in_stock_unit=None,
    )


def _item_number(item: str) -> tuple[int, str]:
    """Sort key for item numbers as integers ("9" before "10"), like the calculation (#20)."""
    return (int(item), item) if item.isdigit() else (0, item)
