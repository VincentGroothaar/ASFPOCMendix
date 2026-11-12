"""The order list: filters, statuses, requisition labels and counts (REQ-1, REQ-4; issue #25).

In Mendix terms this is the data source microflow behind the Orders page. The view only parses
the request into plain values and renders what `build_order_list` returns.

The rules, in the order they are applied (spec in issue #25, "List rules"):
1. Scope: active orders of the plant that start inside the range, plus every overdue order.
2. Statuses come from the whole plant (all active orders), never from the scoped set (INV-6).
3. Requisition filter.
4. Tile counts: after 1 and 3, before the status (tile) filter.
5. Status (tile) filter.
6. Sort by start date, then order number, and show 50 per page.
"""

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum

from django.core.paginator import Page, Paginator

from cockpit.models import ProductionOrder, Requisition, Stock
from cockpit.services.buffer import current_buffer
from cockpit.services.shortage import (
    ComponentLine,
    OrderLine,
    PlantResult,
    ShortageSettings,
    Status,
    StockLine,
    calculate,
)

DEFAULT_RANGE_DAYS = 14  # default range: today to today + 14 days (REQ-1, AC-2)
PAGE_SIZE = 50  # orders per page (REQ-1, AC-6)

# The statuses a tile can filter on, as they appear in the URL (`?status=short`).
TILE_STATUSES = (Status.SHORT, Status.LOW_COVER, Status.COVERED)

# The keys of the shared UI components (`status_pill`, `kpi_tile`) for each order status.
PILL_KEYS: dict[Status, str] = {
    Status.SHORT: "short",
    Status.LOW_COVER: "low",
    Status.COVERED: "covered",
}

# The order shows its most urgent requisition label (D-30). Rejected is never shown.
LABEL_URGENCY = (
    Requisition.Status.FAILED,
    Requisition.Status.AWAITING_APPROVAL,
    Requisition.Status.SENT,
)


class RequisitionFilter(StrEnum):
    """The Requisition select on the order list. The values match `Requisition.Status`."""

    NONE = "none"
    SENT = "sent"
    AWAITING_APPROVAL = "awaiting_approval"
    FAILED = "failed"


@dataclass(frozen=True)
class OrderFilters:
    """What the user filters the order list on. Every field always holds a valid value."""

    plant: str
    start_from: date
    start_to: date
    status: Status | None  # tile filter: SHORT, LOW_COVER or COVERED; None = all
    requisition: RequisitionFilter | None  # None = all
    page: int

    def query(self, **changes: object) -> dict[str, str]:
        """The URL parameters for these filters (with `changes` applied), for links.

        Empty list filters and page 1 are left out, so links stay short.
        """
        filters = replace(self, **changes)
        params = {
            "plant": filters.plant,
            "from": filters.start_from.isoformat(),
            "to": filters.start_to.isoformat(),
        }
        if filters.status is not None:
            params["status"] = filters.status.value
        if filters.requisition is not None:
            params["requisition"] = filters.requisition.value
        if filters.page != 1:
            params["page"] = str(filters.page)
        return params


@dataclass(frozen=True)
class OrderRow:
    """One row of the order table."""

    number: str
    material: str
    description: str
    quantity: Decimal
    unit: str
    start_date: date
    overdue: bool
    status: Status | None  # None: no component counts (only issued or unit mismatch lines)
    pill_key: str | None  # the `status_pill` key for `status`, None when status is None
    unit_mismatch: bool
    requisition: Requisition.Status | None  # the label to show, None = no label


@dataclass(frozen=True)
class OrderCounts:
    """The numbers on the four tiles."""

    all: int
    short: int
    low_cover: int
    covered: int


@dataclass(frozen=True)
class OrderList:
    """Everything the order table shows for one request."""

    counts: OrderCounts
    page: Page  # a Django Page of OrderRow, for the pagination component
    buffer_percent: Decimal  # the cover buffer used for the statuses and tooltips

    @property
    def rows(self) -> list[OrderRow]:
        return list(self.page.object_list)


# --- Filters ------------------------------------------------------------------------------------


def default_filters(plants: Sequence[str], today: date) -> OrderFilters:
    """The filters of a first visit: the first plant, today to today + 14 days, no list filter."""
    return OrderFilters(
        plant=plants[0],
        start_from=today,
        start_to=today + timedelta(days=DEFAULT_RANGE_DAYS),
        status=None,
        requisition=None,
        page=1,
    )


def parse_filters(params: Mapping[str, str], plants: Sequence[str], today: date) -> OrderFilters:
    """Read the filters from the URL parameters. A missing or bad value gets its default.

    Only plants from `plants` (COCKPIT_PLANTS) are accepted, so no other plant ever reaches
    SAP. A start date after the end date is allowed: the list then shows only overdue orders.
    """
    default = default_filters(plants, today)
    plant = params.get("plant", "")
    return OrderFilters(
        plant=plant if plant in plants else default.plant,
        start_from=_parse_date(params.get("from", ""), default.start_from),
        start_to=_parse_date(params.get("to", ""), default.start_to),
        status=_parse_choice(params.get("status", ""), TILE_STATUSES),
        requisition=_parse_choice(params.get("requisition", ""), tuple(RequisitionFilter)),
        page=_parse_page(params.get("page", "")),
    )


def _parse_date(value: str, default: date) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return default


def _parse_choice(value: str, choices: tuple) -> object | None:
    for choice in choices:
        if value == choice.value:
            return choice
    return None


def _parse_page(value: str) -> int:
    # Only plain ASCII digits, at most 9 of them: `isdigit()` also accepts characters such as
    # "²" that int() rejects, and int() refuses very long numbers (review M-1 on #73).
    if re.fullmatch(r"[1-9][0-9]{0,8}", value):
        return int(value)
    return 1


# --- Statuses and labels ------------------------------------------------------------------------


def plant_result(plant: str, today: date) -> PlantResult:
    """Calculate the status of every active order of the plant from the stored snapshot.

    Always over all active orders, whatever the screen shows (INV-6). Reused by the order
    detail (#26) and the dashboard (#30).
    """
    return _calculate(plant, _active_orders(plant), today)


def _active_orders(plant: str) -> list[ProductionOrder]:
    """All active orders of the plant with their components, read once."""
    return list(
        ProductionOrder.objects.filter(plant=plant, is_active=True).prefetch_related("components")
    )


def _calculate(plant: str, orders: list[ProductionOrder], today: date) -> PlantResult:
    """Run the status calculation over exactly these orders and the plant's stock."""
    order_lines = [
        OrderLine(
            number=order.number,
            start_date=order.start_date,
            components=tuple(
                ComponentLine(
                    item=line.item,
                    material=line.material,
                    required=line.required_quantity,
                    withdrawn=line.withdrawn_quantity,
                    unit=line.unit,
                )
                for line in order.components.all()
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


def order_requisition_labels(order_ids: Iterable[int]) -> dict[int, Requisition.Status]:
    """The requisition label of each order: its most urgent open or failed requisition.

    Per order and material only the latest requisition (highest id) counts; a Rejected latest
    one adds no label (decisions 5 and R-I2 on #25). Orders without a label are left out.
    """
    latest = (
        Requisition.objects.filter(order_id__in=list(order_ids))
        .order_by("order_id", "material", "-id")
        .distinct("order_id", "material")
        .values_list("order_id", "status")
    )
    statuses: dict[int, set[str]] = {}
    for order_id, status in latest:
        statuses.setdefault(order_id, set()).add(status)
    labels = {}
    for order_id, found in statuses.items():
        for label in LABEL_URGENCY:
            if label in found:
                labels[order_id] = label
                break
    return labels


# --- The list -----------------------------------------------------------------------------------


def build_order_list(filters: OrderFilters, today: date) -> OrderList:
    """Build the tiles and the requested page of the order table for these filters."""
    # The orders are read once and used for both the statuses and the rows, so a sync that
    # commits in between can never add a row without a status (review S-1 on #73).
    orders = _active_orders(filters.plant)
    result = _calculate(filters.plant, orders, today)
    # Overdue orders are always listed, whatever the range (D-18).
    in_scope = [
        order
        for order in orders
        if order.start_date < today or filters.start_from <= order.start_date <= filters.start_to
    ]
    labels = order_requisition_labels(order.id for order in in_scope)
    rows = [_row(order, result, labels.get(order.id), today) for order in in_scope]

    if filters.requisition is not None:
        rows = [row for row in rows if _matches_requisition(row, filters.requisition)]
    counts = OrderCounts(
        all=len(rows),
        short=sum(row.status == Status.SHORT for row in rows),
        low_cover=sum(row.status == Status.LOW_COVER for row in rows),
        covered=sum(row.status == Status.COVERED for row in rows),
    )
    if filters.status is not None:
        rows = [row for row in rows if row.status == filters.status]

    rows.sort(key=lambda row: (row.start_date, row.number))
    page = Paginator(rows, PAGE_SIZE).get_page(filters.page)
    return OrderList(counts=counts, page=page, buffer_percent=result.buffer_percent)


def _row(
    order: ProductionOrder,
    result: PlantResult,
    label: Requisition.Status | None,
    today: date,
) -> OrderRow:
    calculated = result.orders[order.number]
    return OrderRow(
        number=order.number,
        material=order.material,
        description=order.description,
        quantity=order.quantity,
        unit=order.unit,
        start_date=order.start_date,
        overdue=order.start_date < today,
        status=calculated.status,
        pill_key=PILL_KEYS.get(calculated.status) if calculated.status else None,
        unit_mismatch=calculated.unit_mismatch,
        requisition=label,
    )


def _matches_requisition(row: OrderRow, wanted: RequisitionFilter) -> bool:
    if wanted is RequisitionFilter.NONE:
        return row.requisition is None
    return row.requisition == wanted.value


# --- Tooltip texts ------------------------------------------------------------------------------


def tile_tooltips(buffer_percent: Decimal) -> dict[Status, str]:
    """The ⓘ texts of the three status tiles (ui-spec 5.2), with the current cover buffer."""
    buffer = format_percent(buffer_percent)
    return {
        Status.SHORT: (
            "At least one component has less stock available than it needs, "
            "after earlier orders take their share."
        ),
        Status.LOW_COVER: (
            f"All components are covered, but at least one has less than {buffer} to spare."
        ),
        Status.COVERED: f"All components have at least {buffer} to spare.",
    }


def format_percent(value: Decimal) -> str:
    """A buffer value as shown in the tooltips: `10%`, `12.5%` (no trailing zeros)."""
    text = f"{value:f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return f"{text}%"
