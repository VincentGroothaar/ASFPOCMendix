"""Shortage allocation and status calculation (REQ-4, the "issued" rule of REQ-2, #20).

One pure function, `calculate`, turns the plant's active production orders and its
unrestricted stock into a status per component line and per order. Stock goes to the
orders that start first. Every quantity is a Decimal and nothing is rounded (INV-5).

No database, no SAP, no Django: the callers (#25, #26, #28, #30) map their data into the
input types below. Screen labels and tooltip copy live in the templates (ui-spec 3.1, 5.2).
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import (
    Decimal,
    DivisionByZero,
    Inexact,
    InvalidOperation,
    Overflow,
    Rounded,
    localcontext,
)
from enum import StrEnum

from cockpit.services.units import UnitMismatch, convert

ZERO = Decimal("0")
HUNDRED = Decimal("100")
# With these traps a result that is not exact raises instead of being rounded (INV-5).
_EXACT_TRAPS = [InvalidOperation, DivisionByZero, Overflow, Inexact, Rounded]

# --- Inputs -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ComponentLine:
    """One component line of a production order, in the order's unit."""

    item: str
    material: str
    required: Decimal
    withdrawn: Decimal
    unit: str


@dataclass(frozen=True)
class OrderLine:
    """An active production order with its component lines."""

    number: str
    start_date: date
    components: tuple[ComponentLine, ...]


@dataclass(frozen=True)
class StockLine:
    """Unrestricted stock of one material in the plant, already summed."""

    material: str
    quantity: Decimal
    unit: str


@dataclass(frozen=True)
class ShortageSettings:
    """The settings the calculation uses. #34 makes the buffer editable."""

    buffer_percent: Decimal = Decimal("10")


# --- Outputs ------------------------------------------------------------------------------------


class Status(StrEnum):
    """The status of a component line (and, for the first three, of an order)."""

    SHORT = "short"
    LOW_COVER = "low_cover"
    COVERED = "covered"
    UNIT_MISMATCH = "unit_mismatch"
    ISSUED = "issued"


# Order status is the worst of these line statuses; the other two do not count.
_SEVERITY = {Status.SHORT: 3, Status.LOW_COVER: 2, Status.COVERED: 1}


@dataclass(frozen=True)
class ComponentResult:
    """The result for one component line.

    `open_requirement`, `available` and `shortage` are in the order unit (`unit`).
    `available` and `shortage` are None for Issued and Unit mismatch lines.
    """

    item: str
    material: str
    status: Status
    open_requirement: Decimal
    unit: str
    available: Decimal | None
    shortage: Decimal | None
    stock_unit: str
    available_in_stock_unit: Decimal | None
    shortage_in_stock_unit: Decimal | None


@dataclass(frozen=True)
class OrderResult:
    """The result for one order. `status` is None when no line is Short, Low cover or Covered."""

    number: str
    start_date: date
    status: Status | None
    overdue: bool
    unit_mismatch: bool
    components: tuple[ComponentResult, ...]


@dataclass(frozen=True)
class PlantResult:
    """The result for all orders of a plant, in allocation order."""

    orders: dict[str, OrderResult]
    buffer_percent: Decimal

    def component(self, order_number: str, item: str) -> ComponentResult:
        """The result of one component line. Raises KeyError when there is no such line."""
        for component in self.orders[order_number].components:
            if component.item == item:
                return component
        raise KeyError((order_number, item))


# --- Calculation --------------------------------------------------------------------------------


@dataclass
class _Balance:
    """The running stock of one material while allocating, in its stock unit."""

    unit: str
    quantity: Decimal


@dataclass
class _Allocation:
    """The state shared by all lines while allocating: one balance per material."""

    buffer_percent: Decimal
    balances: dict[str, _Balance] = field(default_factory=dict)


def calculate(
    orders: Iterable[OrderLine],
    stock: Iterable[StockLine],
    settings: ShortageSettings,
    today: date,
) -> PlantResult:
    """Allocate stock to orders by start date and give every line and order a status.

    Pass all active orders of the plant, not only the ones on screen: an order's result
    depends only on the orders that start before it (INV-6).

    Raises:
        ValueError: two stock lines for one material, two orders with one number, or an
            item number that is not a whole number.
        ArithmeticError: a result cannot be held exactly (INV-5).
    """
    orders = list(orders)
    stock = list(stock)
    _check_unique([line.material for line in stock], "stock line for material")
    _check_unique([order.number for order in orders], "order number")

    allocation = _Allocation(
        buffer_percent=settings.buffer_percent,
        balances={line.material: _Balance(line.unit, line.quantity) for line in stock},
    )
    results: dict[str, OrderResult] = {}
    with localcontext(traps=_EXACT_TRAPS):
        for order in sorted(orders, key=lambda order: (order.start_date, order.number)):
            lines = sorted(order.components, key=_item_number)
            components = tuple(_allocate_line(line, allocation) for line in lines)
            results[order.number] = _order_result(order, components, today)
    return PlantResult(orders=results, buffer_percent=settings.buffer_percent)


def _check_unique(keys: list[str], what: str) -> None:
    """Raise ValueError when a key appears twice."""
    seen: set[str] = set()
    for key in keys:
        if key in seen:
            raise ValueError(f"Duplicate {what} {key!r}")
        seen.add(key)


def _item_number(line: ComponentLine) -> int:
    """The item number as a number, so item 10 comes after item 9 ("10" < "9" as text)."""
    if not line.item.isascii() or not line.item.isdigit():
        raise ValueError(f"Component item {line.item!r} is not a whole number")
    return int(line.item)


def _allocate_line(line: ComponentLine, allocation: _Allocation) -> ComponentResult:
    """Give one line its status and take its requirement from the material's balance."""
    open_requirement = max(line.required - line.withdrawn, ZERO)
    balance = allocation.balances.get(line.material)

    if open_requirement == ZERO:
        # Issued: nothing left to cover. It never sets a missing material's stock unit.
        stock_unit = balance.unit if balance else line.unit
        return _result_without_allocation(line, Status.ISSUED, stock_unit)

    if balance is None:
        # No stock row: stock 0 in the unit of the first open line of this material.
        balance = _Balance(line.unit, ZERO)
        allocation.balances[line.material] = balance

    try:
        requirement = convert(open_requirement, line.unit, balance.unit)
    except UnitMismatch:
        return _result_without_allocation(line, Status.UNIT_MISMATCH, balance.unit)

    available = max(balance.quantity, ZERO)
    shortage = max(requirement - available, ZERO)
    status = _line_status(requirement, available, allocation.buffer_percent)
    balance.quantity -= requirement  # Only the requirement; the buffer is never taken.

    return ComponentResult(
        item=line.item,
        material=line.material,
        status=status,
        open_requirement=open_requirement,
        unit=line.unit,
        available=convert(available, balance.unit, line.unit),
        shortage=convert(shortage, balance.unit, line.unit),
        stock_unit=balance.unit,
        available_in_stock_unit=available,
        shortage_in_stock_unit=shortage,
    )


def _line_status(requirement: Decimal, available: Decimal, buffer_percent: Decimal) -> Status:
    """Short, Low cover or Covered, compared in the stock unit without any division."""
    if available < requirement:
        return Status.SHORT
    if available * HUNDRED < (HUNDRED + buffer_percent) * requirement:
        return Status.LOW_COVER
    return Status.COVERED


def _result_without_allocation(
    line: ComponentLine, status: Status, stock_unit: str
) -> ComponentResult:
    """The result of an Issued or Unit mismatch line: no available or shortage."""
    return ComponentResult(
        item=line.item,
        material=line.material,
        status=status,
        open_requirement=max(line.required - line.withdrawn, ZERO),
        unit=line.unit,
        available=None,
        shortage=None,
        stock_unit=stock_unit,
        available_in_stock_unit=None,
        shortage_in_stock_unit=None,
    )


def _order_result(
    order: OrderLine, components: tuple[ComponentResult, ...], today: date
) -> OrderResult:
    """Roll the line results up: worst status, overdue flag and unit mismatch badge."""
    counted = [component.status for component in components if component.status in _SEVERITY]
    return OrderResult(
        number=order.number,
        start_date=order.start_date,
        status=max(counted, key=_SEVERITY.__getitem__) if counted else None,
        overdue=order.start_date < today,
        unit_mismatch=any(c.status == Status.UNIT_MISMATCH for c in components),
        components=components,
    )
