"""The numbers on the shortage dashboard (REQ-6; issue #30).

In Mendix terms this is the data source microflow behind the dashboard page. It is a pure
function: the view reads the database and passes plain values in, this module only counts.

The rules (spec in issue #30):
1. Donut: every order lands in one slice, by its worst status. An order with only unit
   mismatch lines goes under Unit mismatch. An order with no status and no mismatch is left out.
2. Components: Short and Low cover lines only. Unit mismatch and issued lines never count.
3. Shortage per material: materials with at least one Short line, summed in the stock unit.
4. Shortage per order: Short and Low cover orders, red first.
5. Open requisitions: the latest requisition per order and material, Rejected not open.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from cockpit.models import Requisition
from cockpit.services.order_list import PILL_KEYS, RequisitionRow
from cockpit.services.shortage import PlantResult, Status

# The latest requisition counts as open in these statuses. Rejected is not open.
OPEN_REQUISITION_STATUSES = (
    Requisition.Status.AWAITING_APPROVAL,
    Requisition.Status.FAILED,
    Requisition.Status.SENT,
)

# How much of each table the page lists (#80). The rest is counted, not listed.
MATERIAL_ORDERS_SHOWN = 5  # orders per row of Shortage per material
ORDER_ROWS_SHOWN = 10  # rows of Shortage per order

# Donut slices, in legend order: (key, label). The key picks the chart colour token.
SLICES = (
    ("short", "Short"),
    ("low", "Low cover"),
    ("covered", "Covered"),
    ("mismatch", "Unit mismatch"),
)


@dataclass(frozen=True)
class Slice:
    """One donut slice and legend entry."""

    key: str  # short, low, covered or mismatch
    label: str
    count: int


@dataclass(frozen=True)
class MaterialRow:
    """One row of Shortage per material. The shortage is in the material's stock unit."""

    material: str
    description: str
    shortage: Decimal
    unit: str
    orders: int
    order_numbers: tuple[str, ...]  # the affected orders, sorted by start date then number
    first_needed: date
    overdue: bool

    @property
    def shown_orders(self) -> tuple[str, ...]:
        """The first orders listed in the row (#80); the rest is counted in `more_orders`."""
        return self.order_numbers[:MATERIAL_ORDERS_SHOWN]

    @property
    def more_orders(self) -> int:
        """How many affected orders are not listed in the row."""
        return max(0, self.orders - MATERIAL_ORDERS_SHOWN)


@dataclass(frozen=True)
class OrderShortageRow:
    """One row of Shortage per order."""

    number: str
    start_date: date
    overdue: bool
    short_lines: int
    low_lines: int
    pill_key: str  # the `status_pill` key: short or low


@dataclass(frozen=True)
class Dashboard:
    """Everything the dashboard shows for one request."""

    slices: tuple[Slice, ...]
    total: int  # the sum of the slices, shown in the middle of the donut
    red_orders: int
    short_components: int
    short_materials: int
    low_cover_components: int
    open_requisitions: int
    awaiting_approval: int
    materials: tuple[MaterialRow, ...]
    orders: tuple[OrderShortageRow, ...]  # all rows, red first; the page shows `orders_shown`

    @property
    def orders_shown(self) -> tuple[OrderShortageRow, ...]:
        """The first rows of Shortage per order that the page lists (#80)."""
        return self.orders[:ORDER_ROWS_SHOWN]

    @property
    def orders_hidden(self) -> int:
        """How many rows of Shortage per order are not listed."""
        return len(self.orders) - len(self.orders_shown)

    @property
    def short_orders_hidden(self) -> bool:
        """True when at least one hidden row is a Short order (the link to Orders then shows)."""
        return any(row.pill_key == "short" for row in self.orders[ORDER_ROWS_SHOWN:])


def build_dashboard(
    in_scope: Sequence[str],
    result: PlantResult,
    requisitions: Sequence[RequisitionRow],
    today: date,
    descriptions: Mapping[str, str] | None = None,
) -> Dashboard:
    """Count the dashboard numbers for the orders in scope.

    `in_scope` holds the order numbers of the Orders scope, `result` the statuses of the whole
    plant (INV-6), `requisitions` the latest requisition per order and material. An order that
    is in scope but has no result (a sync ran in between) is skipped.
    """
    descriptions = descriptions or {}
    orders = [result.orders[number] for number in in_scope if number in result.orders]
    scope = {order.number for order in orders}

    counts = {"short": 0, "low": 0, "covered": 0, "mismatch": 0}
    short_lines: list[tuple[str, str, Decimal, str, date]] = []
    low_lines = 0
    order_rows: list[OrderShortageRow] = []
    for order in orders:
        key = _slice_key(order.status, order.unit_mismatch)
        if key is not None:
            counts[key] += 1
        order_short = sum(line.status == Status.SHORT for line in order.components)
        order_low = sum(line.status == Status.LOW_COVER for line in order.components)
        low_lines += order_low
        for line in order.components:
            if line.status == Status.SHORT:
                shortage = line.shortage_in_stock_unit or Decimal("0")
                short_lines.append(
                    (line.material, order.number, shortage, line.stock_unit, order.start_date)
                )
        if order.status in (Status.SHORT, Status.LOW_COVER):
            order_rows.append(
                OrderShortageRow(
                    number=order.number,
                    start_date=order.start_date,
                    overdue=order.start_date < today,
                    short_lines=order_short,
                    low_lines=order_low,
                    pill_key=PILL_KEYS[order.status],
                )
            )

    slices = tuple(Slice(key, label, counts[key]) for key, label in SLICES)
    open_rows = [
        row
        for row in requisitions
        if row.order_number in scope and row.status in OPEN_REQUISITION_STATUSES
    ]
    return Dashboard(
        slices=slices,
        total=sum(counts.values()),
        red_orders=counts["short"],
        short_components=len(short_lines),
        short_materials=len({line[0] for line in short_lines}),
        low_cover_components=low_lines,
        open_requisitions=len(open_rows),
        awaiting_approval=sum(
            row.status == Requisition.Status.AWAITING_APPROVAL for row in open_rows
        ),
        materials=_material_rows(short_lines, descriptions, today),
        orders=tuple(sorted(order_rows, key=_order_sort_key)),
    )


def _slice_key(status: Status | None, unit_mismatch: bool) -> str | None:
    """The donut slice of an order (rule 1), or None when it is left out."""
    if status is not None:
        return PILL_KEYS[status]
    return "mismatch" if unit_mismatch else None


def _order_sort_key(row: OrderShortageRow) -> tuple[int, date, str]:
    """Red orders first, then by start date, then by order number (rule 4)."""
    return (0 if row.pill_key == "short" else 1, row.start_date, row.number)


def _material_rows(
    short_lines: list[tuple[str, str, Decimal, str, date]],
    descriptions: Mapping[str, str],
    today: date,
) -> tuple[MaterialRow, ...]:
    """One row per material with a Short line, sorted by first needed (rule 3)."""
    by_material: dict[str, list[tuple[str, str, Decimal, str, date]]] = {}
    for line in short_lines:
        by_material.setdefault(line[0], []).append(line)
    rows = []
    for material, lines in by_material.items():
        first_needed = min(line[4] for line in lines)
        starts = {line[1]: line[4] for line in lines}
        order_numbers = tuple(sorted(starts, key=lambda number: (starts[number], number)))
        rows.append(
            MaterialRow(
                material=material,
                description=descriptions.get(material, ""),
                shortage=sum((line[2] for line in lines), Decimal("0")),
                unit=lines[0][3],
                orders=len(order_numbers),
                order_numbers=order_numbers,
                first_needed=first_needed,
                overdue=first_needed < today,
            )
        )
    return tuple(sorted(rows, key=lambda row: (row.first_needed, row.material)))
