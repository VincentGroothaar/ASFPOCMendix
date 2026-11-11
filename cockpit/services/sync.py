"""Load a plant's data from SAP into the snapshot tables (REQ-1, spec in issue #24).

In Mendix terms this is the microflow that calls the consumed OData service and commits the
result. It is the only code that writes PlantSnapshot, ProductionOrder, Component and Stock.

Three functions for the views:
- `ensure_fresh(plant)`: on a page load. Syncs only when the plant was never synced or the
  snapshot is older than 5 minutes.
- `sync_plant(plant)`: on Refresh, Try again, and after a successful requisition. Always syncs.
- `sync_state(plant)`: only reads what is stored, never calls SAP.

All three return a SyncState and never raise for SAP problems, so a view only has to look at
`synced_at` and `failed` to choose between the page, the warning banner and the error page.

How a sync works (ARCHITECTURE.md, "Sync"):
1. One durable transaction locks the plant's PlantSnapshot row before SAP is called, so the
   same plant is never synced twice at once. Other plants are not blocked.
2. Read orders with components, stock and descriptions from SAP.
3. Check that the data fits the snapshot tables, then write it. If SAP fails or sends unusable
   data, nothing of the snapshot changes; only the error and its time are stored.
"""

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from django.db import models, transaction
from django.utils import timezone

from cockpit.models import Component, PlantSnapshot, ProductionOrder, Stock
from sap import production_orders, products, stock
from sap.client import ODataClient, SapDataError, SapUnavailable

logger = logging.getLogger("cockpit.sync")

# A snapshot older than this is loaded again on the next page view (D-17).
STALE_AFTER = timedelta(minutes=5)

# Quantity columns hold 15 digits, 3 of them decimals (cockpit.models.quantity_field).
QUANTITY_DECIMALS = 3
QUANTITY_INTEGER_DIGITS = 12

# Rows per INSERT or UPDATE statement when writing the snapshot in bulk.
BATCH_SIZE = 500
# The order fields a sync overwrites on an order that is already stored (all but number).
ORDER_FIELDS = [
    "plant",
    "material",
    "description",
    "quantity",
    "unit",
    "start_date",
    "is_active",
    "synced_at",
]


@dataclass(frozen=True)
class SyncState:
    """What a page needs to know about a plant's snapshot.

    - synced_at set, failed False: show the data with "Data as of <synced_at>".
    - synced_at set, failed True: show the data with the "SAP could not be reached" banner.
    - synced_at None, failed True: show the "No data for plant yet" error page.
    """

    plant: str
    synced_at: datetime | None  # last successful sync; None = never
    failed: bool  # True when the latest attempt failed
    error: str  # message of the latest failure, "" when not failed


@dataclass(frozen=True)
class SapData:
    """Everything one sync reads from SAP for a plant."""

    orders: list[production_orders.ProductionOrder]
    stock: dict[str, stock.MaterialStock]
    descriptions: dict[str, str]


@dataclass(frozen=True)
class WriteCounts:
    """How much a sync wrote, for the log line."""

    orders: int
    materials: int


class CountingClient:
    """Wraps the SAP client and counts read calls (`get_all`), for the log line.

    One `get_all` call can read more than one page from SAP; it still counts as one call.
    """

    def __init__(self, client: ODataClient) -> None:
        self._client = client
        self.calls = 0

    def get_all(self, *args, **kwargs) -> list[dict]:
        self.calls += 1
        return self._client.get_all(*args, **kwargs)


# --- Public functions --------------------------------------------------------------------------


def sync_state(plant: str) -> SyncState:
    """Return the stored sync state of a plant without calling SAP."""
    return _state(plant, PlantSnapshot.objects.filter(plant=plant).first())


def sync_plant(plant: str, client: ODataClient | None = None) -> SyncState:
    """Load the plant from SAP now, whatever the age of the snapshot (Refresh, Try again).

    Waits when another sync of the same plant is running. Must not be called inside another
    database transaction: the durable block raises RuntimeError, so a requisition re-syncs
    only after its own transaction has committed (review I-1 on #24).
    """
    with transaction.atomic(durable=True):
        snapshot = _lock(plant)
        return _sync_locked(snapshot, client)


def ensure_fresh(plant: str, client: ODataClient | None = None) -> SyncState:
    """Load the plant from SAP if it was never synced or the snapshot is over 5 minutes old.

    When another request syncs the same plant while this one waits for the lock, this one uses
    that result instead of calling SAP again, also when that attempt failed (review I-2, I-4).
    """
    seen_before_lock = _attempt_marks(PlantSnapshot.objects.filter(plant=plant).first())
    with transaction.atomic(durable=True):
        snapshot = _lock(plant)
        another_attempt_finished = _attempt_marks(snapshot) != seen_before_lock
        if another_attempt_finished or not _is_stale(snapshot):
            return _state(plant, snapshot)
        return _sync_locked(snapshot, client)


# --- Steps of a sync ---------------------------------------------------------------------------


def _lock(plant: str) -> PlantSnapshot:
    """Create the plant's PlantSnapshot row if needed, then lock it until the transaction ends.

    get_or_create handles two first syncs at once: the second insert waits for the first and
    then reads its row. The locked read always returns the latest committed values.
    """
    PlantSnapshot.objects.get_or_create(plant=plant)
    return PlantSnapshot.objects.select_for_update().get(plant=plant)


def _sync_locked(snapshot: PlantSnapshot, client: ODataClient | None) -> SyncState:
    """Read SAP and write the snapshot. The caller holds the lock on `snapshot`."""
    started = time.monotonic()
    sap = CountingClient(client or ODataClient.from_settings())
    synced_at = timezone.now()
    try:
        data = _read_from_sap(sap, snapshot.plant)
        # A savepoint, as the spec asks. All SAP reads and checks happen before it, so today it
        # only matters if a later change makes a SAP call or check while writing.
        with transaction.atomic():
            counts = _write_snapshot(snapshot.plant, data, synced_at)
    except SapUnavailable as error:  # includes SapDataError (decision 2 on #24)
        _store_failure(snapshot, str(error))
        _log(snapshot.plant, "failed", None, sap.calls, started, error=str(error))
        return _state(snapshot.plant, snapshot)

    snapshot.synced_at = synced_at
    snapshot.last_sync_error = ""
    snapshot.last_sync_error_at = None
    snapshot.save(update_fields=["synced_at", "last_sync_error", "last_sync_error_at"])
    _log(snapshot.plant, "ok", counts, sap.calls, started)
    return _state(snapshot.plant, snapshot)


def _read_from_sap(client: CountingClient, plant: str) -> SapData:
    """Read the plant's released orders, the stock of their components and all descriptions."""
    orders = production_orders.read_released_orders(client, plant)
    component_materials = sorted({line.material for order in orders for line in order.components})
    all_materials = sorted(set(component_materials) | {order.material for order in orders})
    data = SapData(
        orders=orders,
        stock=stock.read_unrestricted_stock(client, plant, component_materials),
        descriptions=products.read_descriptions(client, all_materials),
    )
    _check_fits_snapshot(data)
    return data


def _check_fits_snapshot(data: SapData) -> None:
    """Raise SapDataError when SAP sent data the snapshot tables cannot hold (review on #60).

    Without this check such data would crash the sync with a database error (a 500 page, no
    stored error) instead of failing like an outage, as decision 2 on #24 asks. Examples: the
    same order twice (paging over a list that changed between pages), the same item twice in
    one order, a text longer than its column, or a quantity with more than 3 decimals.
    """
    numbers = [order.number for order in data.orders]
    duplicates = sorted({number for number in numbers if numbers.count(number) > 1})
    if duplicates:
        raise SapDataError(f"SAP sent production order {duplicates[0]} more than once.")
    for order in data.orders:
        _check_text(ProductionOrder, "number", order.number)
        _check_text(ProductionOrder, "material", order.material)
        _check_text(ProductionOrder, "unit", order.unit)
        _check_quantity(order.quantity, f"order {order.number}")
        items = [line.item for line in order.components]
        if len(set(items)) != len(items):
            raise SapDataError(f"SAP sent an item twice in production order {order.number}.")
        for line in order.components:
            _check_text(Component, "item", line.item)
            _check_text(Component, "material", line.material)
            _check_text(Component, "unit", line.unit)
            _check_quantity(line.required_quantity, f"order {order.number} item {line.item}")
            _check_quantity(line.withdrawn_quantity, f"order {order.number} item {line.item}")
    for material_stock in data.stock.values():
        _check_text(Stock, "unit", material_stock.unit)
        _check_quantity(material_stock.quantity, f"stock of {material_stock.material}")
    for description in data.descriptions.values():
        _check_text(Component, "description", description)


def _check_text(model: type[models.Model], field: str, value: str) -> None:
    """Raise SapDataError when `value` is longer than the model's column for `field`."""
    max_length = model._meta.get_field(field).max_length
    if len(value) > max_length:
        # Only the start of the text: the message is stored and can be shown on screen.
        raise SapDataError(
            f"SAP sent a {field} longer than {max_length} characters: {value[:60]!r}."
        )


def _check_quantity(value: Decimal, where: str) -> None:
    """Raise SapDataError when a quantity does not fit 15 digits with 3 decimals (INV-5)."""
    if not _fits_quantity_column(value):
        raise SapDataError(f"SAP sent a quantity for {where} that does not fit: {str(value)[:60]}.")


def _fits_quantity_column(value: Decimal) -> bool:
    """True when `value` fits a quantity column: at most 12 digits before the point, 3 after.

    Decided by counting the number's digits and its exponent (Decimal.as_tuple), with no
    Decimal arithmetic at all: arithmetic can itself fail on absurd values such as 1E+1000000,
    and every failure here must be a SapDataError (review round 3 on #60).
    Examples: 1.0000 and 999999999999.999 fit; 1.0005 and 1000000000000 do not.
    """
    if not value.is_finite():
        return False
    _sign, digits, exponent = value.as_tuple()
    # Trailing zeros after the point do not count: 1.0000 is 1.
    while len(digits) > 1 and digits[-1] == 0 and exponent < 0:
        digits = digits[:-1]
        exponent += 1
    if not any(digits):
        return True  # zero, also written as 0E+20 or -0.000000
    integer_digits = len(digits) + exponent
    return exponent >= -QUANTITY_DECIMALS and integer_digits <= QUANTITY_INTEGER_DIGITS


def _write_snapshot(plant: str, data: SapData, synced_at: datetime) -> WriteCounts:
    """Replace the plant's snapshot with what SAP returned (decision 3 on #24).

    - Orders SAP returned are updated or added, and active (again). Their lines are rebuilt.
    - Active orders SAP no longer returns become inactive. Their rows and requisitions stay.
    - All stock rows of the plant are replaced. A material without stock in SAP gets no row.

    Everything is written in bulk (a handful of queries, not a few per order), because a
    plant like AUC1 has over 700 orders and the cold load must stay within 5 s (REQ-1).
    """
    orders = _write_orders(plant, data, synced_at)

    Component.objects.filter(order__in=orders.values()).delete()
    Component.objects.bulk_create(
        (
            Component(
                order=orders[sap_order.number],
                item=line.item,
                material=line.material,
                description=data.descriptions.get(line.material, ""),
                required_quantity=line.required_quantity,
                withdrawn_quantity=line.withdrawn_quantity,
                unit=line.unit,
            )
            for sap_order in data.orders
            for line in sap_order.components
        ),
        batch_size=BATCH_SIZE,
    )

    ProductionOrder.objects.filter(plant=plant, is_active=True).exclude(
        number__in=list(orders)
    ).update(is_active=False)

    Stock.objects.filter(plant=plant).delete()
    Stock.objects.bulk_create(
        Stock(
            plant=plant,
            material=material_stock.material,
            quantity=material_stock.quantity,
            unit=material_stock.unit,
            synced_at=synced_at,
        )
        for material_stock in data.stock.values()
    )
    materials = {line.material for order in data.orders for line in order.components}
    return WriteCounts(orders=len(data.orders), materials=len(materials))


def _write_orders(plant: str, data: SapData, synced_at: datetime) -> dict[str, ProductionOrder]:
    """Add the orders SAP returned, or update them when they are already stored.

    One "insert, or update on a duplicate number" statement per batch (Postgres
    INSERT ... ON CONFLICT), so new and stored orders take the same, fastest path. Each order
    is active again, even if it was inactive. Returns every returned order by number, with its
    database id filled in.
    """
    orders = [
        ProductionOrder(
            number=sap_order.number,
            plant=plant,
            material=sap_order.material,
            description=data.descriptions.get(sap_order.material, ""),
            quantity=sap_order.quantity,
            unit=sap_order.unit,
            start_date=sap_order.start_date,
            is_active=True,
            synced_at=synced_at,
        )
        for sap_order in data.orders
    ]
    ProductionOrder.objects.bulk_create(
        orders,
        batch_size=BATCH_SIZE,
        update_conflicts=True,
        unique_fields=["number"],
        update_fields=ORDER_FIELDS,
    )
    return {order.number: order for order in orders}


def _store_failure(snapshot: PlantSnapshot, message: str) -> None:
    """Store the error of a failed sync. Only the error fields are saved, nothing else."""
    snapshot.last_sync_error = message
    snapshot.last_sync_error_at = timezone.now()
    snapshot.save(update_fields=["last_sync_error", "last_sync_error_at"])


# --- Small helpers -----------------------------------------------------------------------------


def _is_stale(snapshot: PlantSnapshot) -> bool:
    """True when the plant was never synced or the last successful sync is over 5 minutes old."""
    return snapshot.synced_at is None or timezone.now() - snapshot.synced_at > STALE_AFTER


def _attempt_marks(snapshot: PlantSnapshot | None) -> tuple[datetime | None, datetime | None]:
    """The values every finished attempt changes: last success time and last failure time."""
    if snapshot is None:
        return (None, None)
    return (snapshot.synced_at, snapshot.last_sync_error_at)


def _state(plant: str, snapshot: PlantSnapshot | None) -> SyncState:
    """Turn the stored PlantSnapshot row (or no row) into a SyncState."""
    if snapshot is None:
        return SyncState(plant=plant, synced_at=None, failed=False, error="")
    failed = snapshot.last_sync_error_at is not None
    return SyncState(
        plant=plant,
        synced_at=snapshot.synced_at,
        failed=failed,
        error=snapshot.last_sync_error if failed else "",
    )


def _log(
    plant: str,
    result: str,
    counts: WriteCounts | None,
    sap_calls: int,
    started: float,
    error: str = "",
) -> None:
    """Write the one log line per sync that the 5 s target is measured from (REQ-1, AC-5)."""
    seconds = time.monotonic() - started
    if counts is None:
        logger.info(
            "sync plant=%s result=%s sap_calls=%d seconds=%.2f error=%s",
            plant,
            result,
            sap_calls,
            seconds,
            error,
        )
    else:
        logger.info(
            "sync plant=%s result=%s orders=%d materials=%d sap_calls=%d seconds=%.2f",
            plant,
            result,
            counts.orders,
            counts.materials,
            sap_calls,
            seconds,
        )
