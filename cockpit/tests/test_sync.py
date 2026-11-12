"""Tests for the plant sync service (cockpit/services/sync.py, spec S-1 to S-16 in issue #24).

SAP is replaced by the fake HTTP layer from sap/tests, so the real read functions run and every
call is recorded. The clock is frozen with time_machine. Tests marked `transaction=True` use
real transactions, so they can check what another database connection sees.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
import time_machine
from django.contrib.auth.models import User
from django.db import connection, transaction

from cockpit.models import Component, PlantSnapshot, ProductionOrder, Requisition, Stock
from cockpit.services import sync
from cockpit.services.sync import SyncState, ensure_fresh, sync_plant, sync_state
from sap.tests.fake_http import Call, FakeSap, client_for, response

PLANT = "AUC1"
NOW = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)
ORDERS = "A_ProductionOrder_2"
STOCK = "A_MatlStkInAcctMod"
DESCRIPTIONS = "A_ProductDescription"


# --- SAP rows, as the sandbox sends them ------------------------------------------------------


def sap_date(day: date) -> str:
    """An OData V2 date: /Date(<milliseconds since 1970, UTC>)/."""
    midnight = datetime(day.year, day.month, day.day, tzinfo=UTC)
    return f"/Date({int(midnight.timestamp() * 1000)})/"


def component_row(item: str, material: str, required: str, withdrawn: str = "0") -> dict:
    return {
        "ReservationItem": item,
        "Material": material,
        "RequiredQuantity": required,
        "WithdrawnQuantity": withdrawn,
        "BaseUnit": "PC",
    }


def order_row(number: str, start: date, *components: dict, quantity: str = "10") -> dict:
    """A released, open order of PLANT for material FG-1."""
    return {
        "ManufacturingOrder": number,
        "ProductionPlant": PLANT,
        "Material": "FG-1",
        "TotalQuantity": quantity,
        "ProductionUnit": "PC",
        "MfgOrderScheduledStartDate": sap_date(start),
        "MfgOrderPlannedStartDate": sap_date(start),
        "OrderIsReleased": "X",
        "OrderIsDelivered": "",
        "OrderIsTechnicallyCompleted": "",
        "OrderIsClosed": "",
        "OrderIsDeleted": "",
        "OrderIsMarkedForDeletion": "",
        "to_ProductionOrderComponent": {"results": list(components)},
    }


def stock_row(material: str, quantity: str, location: str = "0001", unit: str = "PC") -> dict:
    """Unrestricted-use, non-special stock in one storage location."""
    return {
        "Material": material,
        "Plant": PLANT,
        "StorageLocation": location,
        "InventoryStockType": "01",
        "InventorySpecialStockType": "",
        "MatlWrhsStkQtyInMatlBaseUnit": quantity,
        "MaterialBaseUnit": unit,
    }


def description_row(material: str, text: str) -> dict:
    return {"Product": material, "Language": "EN", "ProductDescription": text}


def standard_rows() -> dict[str, list[dict]]:
    """Two orders, three component materials, stock for two of them (RM-3 has none)."""
    return {
        ORDERS: [
            order_row(
                "1000101",
                date(2026, 11, 4),
                component_row("0001", "RM-1", "100", "40"),
                component_row("0002", "RM-2", "5.5"),
            ),
            order_row("1000102", date(2026, 11, 5), component_row("0001", "RM-3", "2")),
        ],
        STOCK: [stock_row("RM-1", "30", "0001"), stock_row("RM-1", "12.5", "0002")]
        + [stock_row("RM-2", "7")],
        DESCRIPTIONS: [
            description_row("FG-1", "Bike"),
            description_row("RM-1", "Frame"),
            description_row("RM-2", "Wheel"),
            description_row("RM-3", "Bell"),
        ],
    }


class GatedSap(FakeSap):
    """A fake SAP that can fail, and can hold its next answer until a test releases it."""

    def __init__(self, rows: dict[str, list[dict]]) -> None:
        super().__init__(rows=rows)
        self.failing_sets: set[str] = set()  # entity sets that answer HTTP 500
        self.hold_next = False
        self.entered = threading.Event()  # set when a held call has arrived
        self.release = threading.Event()

    def send(self, request, timeout=None, **kwargs):
        if self.hold_next:
            self.hold_next = False
            self.entered.set()
            assert self.release.wait(10), "the test never released the held SAP call"
        entity_set = request.url.split("?")[0].rsplit("/", 1)[-1]
        if entity_set in self.failing_sets:
            self.calls.append(Call(request.method, request.url, dict(request.headers), timeout))
            return response(500, {"error": {"message": {"value": "Internal error"}}})
        return super().send(request, timeout=timeout, **kwargs)

    def fail_everything(self) -> None:
        self.failing_sets = {ORDERS, STOCK, DESCRIPTIONS}

    def order_calls(self) -> int:
        return sum(1 for call in self.calls if call.path.endswith(ORDERS))


@pytest.fixture
def sap() -> GatedSap:
    return GatedSap(standard_rows())


@pytest.fixture
def client(sap: GatedSap):
    return client_for(sap)


@pytest.fixture
def clock() -> Iterator[time_machine.Coordinates]:
    with time_machine.travel(NOW, tick=False) as traveller:
        yield traveller


def in_new_connection(read: Callable[[], object]) -> object:
    """Run `read` on a separate database connection: it only sees committed data."""
    result: dict[str, object] = {}

    def run() -> None:
        try:
            result["value"] = read()
        finally:
            connection.close()

    thread = threading.Thread(target=run)
    thread.start()
    thread.join()
    return result["value"]


def make_requisition(order: ProductionOrder) -> Requisition:
    user = User.objects.create_user("planner-sync-test")
    return Requisition.objects.create(
        order=order,
        material="RM-1",
        items="0001",
        quantity_entered=Decimal("60"),
        unit_entered="PC",
        quantity_sent=Decimal("60"),
        unit_sent="PC",
        delivery_date=order.start_date,
        status=Requisition.Status.SENT,
        created_by=user,
    )


# --- S-1: first sync --------------------------------------------------------------------------


@pytest.mark.django_db
def test_s1_first_sync_stores_orders_components_and_stock(sap, client, clock) -> None:
    state = sync_plant(PLANT, client)

    assert state == SyncState(plant=PLANT, synced_at=NOW, failed=False, failed_at=None, error="")
    order = ProductionOrder.objects.get(number="1000101")
    assert (order.plant, order.material, order.description) == (PLANT, "FG-1", "Bike")
    assert (order.quantity, order.unit, order.start_date) == (
        Decimal("10"),
        "PC",
        date(2026, 11, 4),
    )
    assert order.is_active and order.synced_at == NOW
    lines = [
        (c.item, c.material, c.description, c.required_quantity, c.withdrawn_quantity, c.unit)
        for c in order.components.all()
    ]
    assert lines == [
        ("0001", "RM-1", "Frame", Decimal("100"), Decimal("40"), "PC"),
        ("0002", "RM-2", "Wheel", Decimal("5.5"), Decimal("0"), "PC"),
    ]
    stock = {s.material: (s.quantity, s.unit) for s in Stock.objects.filter(plant=PLANT)}
    # RM-1 is summed over two storage locations; RM-3 has no stock in SAP, so no row (stock 0).
    assert stock == {"RM-1": (Decimal("42.5"), "PC"), "RM-2": (Decimal("7"), "PC")}
    assert PlantSnapshot.objects.get(plant=PLANT).synced_at == NOW


@pytest.mark.django_db
def test_s1_ensure_fresh_syncs_a_plant_that_was_never_synced(sap, client, clock) -> None:
    assert sync_state(PLANT) == SyncState(
        plant=PLANT, synced_at=None, failed=False, failed_at=None, error=""
    )

    state = ensure_fresh(PLANT, client)

    assert state.synced_at == NOW and not state.failed
    assert sap.order_calls() == 1
    assert ProductionOrder.objects.filter(plant=PLANT).count() == 2


# --- S-2, S-3: freshness ----------------------------------------------------------------------


@pytest.mark.django_db
def test_s2_ensure_fresh_syncs_only_when_older_than_5_minutes(sap, client, clock) -> None:
    ensure_fresh(PLANT, client)

    clock.move_to(NOW + timedelta(minutes=4))
    assert ensure_fresh(PLANT, client).synced_at == NOW
    clock.move_to(NOW + timedelta(minutes=5))
    assert ensure_fresh(PLANT, client).synced_at == NOW, "exactly 5 minutes is still fresh"
    assert sap.order_calls() == 1

    clock.move_to(NOW + timedelta(minutes=6))
    state = ensure_fresh(PLANT, client)
    assert sap.order_calls() == 2
    assert state.synced_at == NOW + timedelta(minutes=6)


@pytest.mark.django_db
def test_s3_sync_plant_always_calls_sap(sap, client, clock) -> None:
    sync_plant(PLANT, client)
    clock.move_to(NOW + timedelta(minutes=1))

    state = sync_plant(PLANT, client)

    assert sap.order_calls() == 2
    assert state.synced_at == NOW + timedelta(minutes=1)


# --- S-4, S-5: what a later sync writes -------------------------------------------------------


@pytest.mark.django_db
def test_s4_order_gone_from_sap_becomes_inactive_and_keeps_its_requisition(
    sap, client, clock
) -> None:
    sync_plant(PLANT, client)
    requisition = make_requisition(ProductionOrder.objects.get(number="1000101"))
    gone = sap.rows[ORDERS].pop(0)

    sync_plant(PLANT, client)

    order = ProductionOrder.objects.get(number="1000101")
    assert not order.is_active
    assert [c.material for c in order.components.all()] == ["RM-1", "RM-2"], (
        "rows stay as they were"
    )
    assert list(order.requisitions.all()) == [requisition]
    assert ProductionOrder.objects.get(number="1000102").is_active

    sap.rows[ORDERS].append(gone)
    sync_plant(PLANT, client)
    assert ProductionOrder.objects.get(number="1000101").is_active, "released again: active again"


@pytest.mark.django_db
def test_s5_changed_orders_lines_and_stock_replace_the_old_ones(sap, client, clock) -> None:
    sync_plant(PLANT, client)
    sap.rows[ORDERS][0] = order_row(
        "1000101", date(2026, 11, 6), component_row("0003", "RM-3", "9"), quantity="12"
    )
    sap.rows[ORDERS].pop(1)
    sap.rows[STOCK] = [stock_row("RM-3", "4")]
    clock.move_to(NOW + timedelta(minutes=1))

    sync_plant(PLANT, client)

    order = ProductionOrder.objects.get(number="1000101")
    assert (order.quantity, order.start_date) == (Decimal("12"), date(2026, 11, 6))
    assert order.synced_at == NOW + timedelta(minutes=1)
    assert [(c.item, c.material) for c in order.components.all()] == [("0003", "RM-3")]
    stock = {s.material: s.quantity for s in Stock.objects.filter(plant=PLANT)}
    # RM-1 and RM-2 are no longer needed; their rows are gone.
    assert stock == {"RM-3": Decimal("4")}


@pytest.mark.django_db
def test_s5_other_plants_are_not_touched(sap, client, clock) -> None:
    other = ProductionOrder.objects.create(
        number="2000001",
        plant="USC1",
        material="FG-9",
        quantity=Decimal("1"),
        unit="PC",
        start_date=date(2026, 11, 4),
        synced_at=NOW,
    )
    Stock.objects.create(plant="USC1", material="RM-1", quantity=1, unit="PC", synced_at=NOW)

    sync_plant(PLANT, client)

    other.refresh_from_db()
    assert other.is_active
    assert Stock.objects.filter(plant="USC1").count() == 1


# --- S-6 to S-10: failures --------------------------------------------------------------------


def stored_snapshot() -> dict:
    """The parts of the snapshot a failed sync must leave alone, plus the stored error."""
    row = PlantSnapshot.objects.get(plant=PLANT)
    return {
        "orders": sorted(ProductionOrder.objects.values_list("number", "is_active", "quantity")),
        "lines": Component.objects.count(),
        "stock": sorted(Stock.objects.values_list("material", "quantity")),
        "synced_at": row.synced_at,
        "error": row.last_sync_error,
        "error_at": row.last_sync_error_at,
    }


@pytest.mark.django_db(transaction=True)
def test_s6_failure_after_a_success_keeps_the_snapshot_and_commits_the_error(
    sap, client, clock
) -> None:
    sync_plant(PLANT, client)
    before = in_new_connection(stored_snapshot)
    sap.rows[ORDERS][0]["TotalQuantity"] = "99"  # a change that must not be written
    sap.fail_everything()
    clock.move_to(NOW + timedelta(minutes=6))

    state = ensure_fresh(PLANT, client)

    assert state == SyncState(
        plant=PLANT,
        synced_at=NOW,
        failed=True,
        failed_at=NOW + timedelta(minutes=6),
        error="SAP answered with HTTP 500.",
    )
    after = in_new_connection(stored_snapshot)
    assert {**after, "error": "", "error_at": None} == before
    assert after["error"] == "SAP answered with HTTP 500."
    assert after["error_at"] == NOW + timedelta(minutes=6)


@pytest.mark.django_db(transaction=True)
def test_s7_first_ever_failure_stores_no_data_and_commits_the_error(sap, client, clock) -> None:
    sap.fail_everything()

    state = ensure_fresh(PLANT, client)

    assert state == SyncState(
        plant=PLANT, synced_at=None, failed=True, failed_at=NOW, error="SAP answered with HTTP 500."
    )
    after = in_new_connection(stored_snapshot)
    assert after["orders"] == [] and after["lines"] == 0 and after["stock"] == []
    assert after["synced_at"] is None
    assert after["error"] == "SAP answered with HTTP 500." and after["error_at"] == NOW


@pytest.mark.django_db
def test_s8_unusable_sap_data_fails_the_sync_like_an_outage(sap, client, clock) -> None:
    sync_plant(PLANT, client)
    before = stored_snapshot()
    # One material's stock in two different units: SapDataError (note from #18).
    sap.rows[STOCK].append(stock_row("RM-2", "1", "0003", unit="KG"))
    clock.move_to(NOW + timedelta(minutes=1))

    state = sync_plant(PLANT, client)

    assert state.failed and state.synced_at == NOW
    assert "RM-2" in state.error
    after = stored_snapshot()
    assert {**after, "error": "", "error_at": None} == before


def duplicate_order(rows: dict) -> None:
    rows[ORDERS].append(dict(rows[ORDERS][0]))  # e.g. paging over a list that changed


def duplicate_item(rows: dict) -> None:
    lines = rows[ORDERS][0]["to_ProductionOrderComponent"]["results"]
    lines.append(dict(lines[0]))


def long_description(rows: dict) -> None:
    rows[DESCRIPTIONS][1]["ProductDescription"] = "x" * 500


def four_decimals(rows: dict) -> None:
    rows[ORDERS][0]["to_ProductionOrderComponent"]["results"][0]["RequiredQuantity"] = "1.0005"


def huge_quantity(rows: dict) -> None:
    rows[STOCK][0]["MatlWrhsStkQtyInMatlBaseUnit"] = "1000000000000"


def enormous_quantity(rows: dict) -> None:
    rows[STOCK][0]["MatlWrhsStkQtyInMatlBaseUnit"] = "1E+25"  # too big even to round


def absurd_exponent(rows: dict) -> None:
    rows[STOCK][0]["MatlWrhsStkQtyInMatlBaseUnit"] = "1E+1000000"  # breaks Decimal arithmetic


def long_unit(rows: dict) -> None:
    rows[ORDERS][0]["ProductionUnit"] = "PCSX"


def long_order_number(rows: dict) -> None:
    rows[ORDERS][1]["ManufacturingOrder"] = "1" * 13


@pytest.mark.django_db
@pytest.mark.parametrize(
    "spoil",
    [
        duplicate_order,
        duplicate_item,
        long_description,
        long_unit,
        long_order_number,
        four_decimals,
        huge_quantity,
        enormous_quantity,
        absurd_exponent,
    ],
)
def test_s8_data_the_snapshot_cannot_hold_fails_like_an_outage(sap, client, clock, spoil) -> None:
    sync_plant(PLANT, client)
    before = stored_snapshot()
    spoil(sap.rows)
    clock.move_to(NOW + timedelta(minutes=1))

    state = sync_plant(PLANT, client)

    assert state.failed and state.synced_at == NOW, "no database error, a failed sync instead"
    assert state.error.startswith("SAP sent")
    assert len(state.error) < 150, "the SAP text in the message is cut short"
    assert {**stored_snapshot(), "error": "", "error_at": None} == before


@pytest.mark.parametrize(
    ("quantity", "fits"),
    [
        ("0", True),
        ("-0", True),
        ("0E+20", True),
        ("1.0000", True),
        ("999999999999.999", True),
        ("-999999999999.999", True),
        ("1E+3", True),
        ("1.0005", False),
        ("1E-30", False),
        ("1000000000000", False),
        ("1E+25", False),
        ("1E+1000000", False),
        ("1E-1000000", False),
        ("NaN", False),
        ("Infinity", False),
    ],
)
def test_s8_quantity_column_check_never_needs_decimal_arithmetic(quantity, fits) -> None:
    assert sync._fits_quantity_column(Decimal(quantity)) is fits


@pytest.mark.django_db
def test_s8_first_sync_with_unusable_data_has_no_snapshot(sap, client, clock) -> None:
    sap.rows[ORDERS][0]["MfgOrderScheduledStartDate"] = "not a date"

    state = sync_plant(PLANT, client)

    assert state.failed and state.synced_at is None
    assert ProductionOrder.objects.count() == 0


@pytest.mark.django_db
def test_s9_failure_after_orders_were_read_writes_nothing(sap, client, clock) -> None:
    sap.failing_sets = {STOCK}  # orders answer, stock fails

    state = sync_plant(PLANT, client)

    assert state.failed
    assert ProductionOrder.objects.count() == 0
    assert Component.objects.count() == 0
    assert Stock.objects.count() == 0


@pytest.mark.django_db
def test_s10_success_after_a_failure_clears_the_error(sap, client, clock) -> None:
    sap.fail_everything()
    sync_plant(PLANT, client)
    sap.failing_sets = set()
    clock.move_to(NOW + timedelta(minutes=1))

    state = sync_plant(PLANT, client)

    assert state == SyncState(
        plant=PLANT, synced_at=NOW + timedelta(minutes=1), failed=False, failed_at=None, error=""
    )
    row = PlantSnapshot.objects.get(plant=PLANT)
    assert row.last_sync_error == "" and row.last_sync_error_at is None


# --- S-11: two requests at once ---------------------------------------------------------------


def wait_until_a_query_waits_for_a_lock() -> None:
    """Wait until another connection of this test waits for the PlantSnapshot row lock.

    Only a session of this test database that is blocked by another session's lock and runs a
    SELECT ... FOR UPDATE on the snapshot table counts, so other sessions cannot match.
    """
    deadline = time.monotonic() + 10
    with connection.cursor() as cursor:
        while time.monotonic() < deadline:
            cursor.execute(
                "select count(*) from pg_stat_activity "
                "where datname = current_database() and pid <> pg_backend_pid() "
                "and cardinality(pg_blocking_pids(pid)) > 0 "
                "and query ilike %s and query ilike %s",
                ["%cockpit_plantsnapshot%", "%for update%"],
            )
            if cursor.fetchone()[0]:
                return
            time.sleep(0.02)
    raise AssertionError("the second request never waited for the plant lock")


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("first_attempt_fails", [False, True])
def test_s11_a_load_waiting_behind_a_sync_uses_its_result(sap, clock, first_attempt_fails) -> None:
    sync_plant(PLANT, client_for(sap))
    clock.move_to(NOW + timedelta(minutes=6))  # stale: both loads below want to sync
    calls_before = sap.order_calls()
    if first_attempt_fails:
        sap.fail_everything()
    sap.hold_next = True
    results: dict[str, SyncState] = {}

    def load(name: str) -> None:
        try:
            results[name] = ensure_fresh(PLANT, client_for(sap))
        finally:
            connection.close()

    first = threading.Thread(target=load, args=("first",))
    second = threading.Thread(target=load, args=("second",))
    try:
        first.start()
        assert sap.entered.wait(10), "the first load never called SAP"
        second.start()
        wait_until_a_query_waits_for_a_lock()
    finally:
        # Always let both threads finish, also when an assertion above failed.
        sap.release.set()
        for thread in (first, second):
            if thread.ident is not None:  # started
                thread.join(10)
    assert not first.is_alive() and not second.is_alive(), "a load never finished"

    assert sap.order_calls() == calls_before + 1, "only the first load called SAP"
    assert results["second"] == results["first"]
    assert results["first"].failed is first_attempt_fails


# --- S-12: the log line -----------------------------------------------------------------------


@pytest.mark.django_db
def test_s12_each_sync_logs_one_line_with_counts_and_seconds(sap, client, clock, caplog) -> None:
    caplog.set_level(logging.INFO, logger="cockpit.sync")

    sync_plant(PLANT, client)
    sap.fail_everything()
    sync_plant(PLANT, client)

    lines = [record.getMessage() for record in caplog.records if record.name == "cockpit.sync"]
    assert len(lines) == 2
    # 3 reads: orders, stock (one batch), descriptions (one batch).
    assert lines[0].startswith("sync plant=AUC1 result=ok orders=2 materials=3 sap_calls=3 ")
    assert "seconds=" in lines[0]
    assert lines[1].startswith("sync plant=AUC1 result=failed sap_calls=1 seconds=")
    assert lines[1].endswith("error=SAP answered with HTTP 500.")


# --- S-14, S-15, S-16 -------------------------------------------------------------------------


@pytest.mark.django_db
def test_s14_quantities_are_stored_as_exact_decimals(sap, client, clock) -> None:
    sap.rows[ORDERS][0]["to_ProductionOrderComponent"]["results"][0]["RequiredQuantity"] = "109.999"

    sync_plant(PLANT, client)

    line = Component.objects.get(order__number="1000101", item="0001")
    assert line.required_quantity == Decimal("109.999")
    assert isinstance(line.required_quantity, Decimal)


@pytest.mark.django_db
def test_s14_the_sync_only_reads_from_sap(sap, client, clock) -> None:
    sync_plant(PLANT, client)

    # Every request a full sync sends is a GET (INV-4), and the client has no write method.
    assert sap.calls and {call.method for call in sap.calls} == {"GET"}
    assert not any(hasattr(sync.ODataClient, name) for name in ("post", "put", "patch", "delete"))


@pytest.mark.django_db
def test_s15_sync_plant_inside_a_transaction_raises_and_calls_no_sap(sap, client, clock) -> None:
    with pytest.raises(RuntimeError), transaction.atomic():
        sync_plant(PLANT, client)

    assert sap.calls == []


@pytest.mark.django_db
def test_s16_after_a_failed_refresh_a_fresh_load_shows_the_failure_without_calling_sap(
    sap, client, clock
) -> None:
    sync_plant(PLANT, client)
    sap.fail_everything()
    clock.move_to(NOW + timedelta(minutes=1))
    sync_plant(PLANT, client)  # the failed Refresh
    calls = sap.order_calls()
    clock.move_to(NOW + timedelta(minutes=2))

    state = ensure_fresh(PLANT, client)

    assert sap.order_calls() == calls
    assert state == SyncState(
        plant=PLANT,
        synced_at=NOW,
        failed=True,
        failed_at=NOW + timedelta(minutes=1),
        error="SAP answered with HTTP 500.",
    )


# --- Issue #69: failure time and missing SAP configuration -----------------------------------

NOT_CONFIGURED = "The SAP connection is not configured."


@pytest.mark.django_db
def test_69_s1_failed_at_is_the_stored_failure_time_and_none_after_success(
    sap, client, clock
) -> None:
    sap.fail_everything()
    failed = sync_plant(PLANT, client)
    assert failed.failed_at == NOW == PlantSnapshot.objects.get(plant=PLANT).last_sync_error_at

    sap.failing_sets = set()
    clock.move_to(NOW + timedelta(minutes=1))
    assert sync_plant(PLANT, client).failed_at is None


@pytest.mark.django_db
@pytest.mark.parametrize("missing", ["SAP_BASE_URL", "SAP_API_KEY"])
def test_69_s2_s3_missing_config_on_a_never_synced_plant_fails_and_stores_nothing(
    settings, clock, missing
) -> None:
    settings.SAP_BASE_URL = "https://sap.test"
    settings.SAP_API_KEY = "key"
    setattr(settings, missing, "")

    for sync_function in (sync_plant, ensure_fresh):
        state = sync_function(PLANT)

        assert state == SyncState(
            plant=PLANT, synced_at=None, failed=True, failed_at=NOW, error=NOT_CONFIGURED
        )
        assert not PlantSnapshot.objects.filter(plant=PLANT).exists()


@pytest.mark.django_db
def test_69_s2_s3_missing_config_on_a_stale_snapshot_keeps_the_stored_row(
    sap, client, clock, settings
) -> None:
    sync_plant(PLANT, client)
    before = PlantSnapshot.objects.values().get(plant=PLANT)
    settings.SAP_API_KEY = ""
    clock.move_to(NOW + timedelta(minutes=6))

    refreshed = sync_plant(PLANT)
    loaded = ensure_fresh(PLANT)

    expected = SyncState(
        plant=PLANT,
        synced_at=NOW,
        failed=True,
        failed_at=NOW + timedelta(minutes=6),
        error=NOT_CONFIGURED,
    )
    assert refreshed == loaded == expected
    assert PlantSnapshot.objects.values().get(plant=PLANT) == before


@pytest.mark.django_db
def test_69_missing_config_on_a_fresh_snapshot_does_not_build_a_client(
    sap, client, clock, settings
) -> None:
    sync_plant(PLANT, client)
    settings.SAP_API_KEY = ""
    clock.move_to(NOW + timedelta(minutes=4))

    assert ensure_fresh(PLANT) == SyncState(
        plant=PLANT, synced_at=NOW, failed=False, failed_at=None, error=""
    )


@pytest.mark.django_db(transaction=True)
def test_69_s3_missing_config_rolls_back_the_first_open_row_for_other_connections(
    clock, settings
) -> None:
    settings.SAP_API_KEY = ""

    ensure_fresh(PLANT)

    assert in_new_connection(lambda: PlantSnapshot.objects.filter(plant=PLANT).count()) == 0


@pytest.mark.django_db
def test_69_missing_config_logs_one_failed_line(clock, settings, caplog) -> None:
    caplog.set_level(logging.INFO, logger="cockpit.sync")
    settings.SAP_API_KEY = ""

    sync_plant(PLANT)

    lines = [record.getMessage() for record in caplog.records if record.name == "cockpit.sync"]
    assert len(lines) == 1
    assert lines[0].startswith("sync plant=AUC1 result=failed sap_calls=0 ")
    assert lines[0].endswith(f"error={NOT_CONFIGURED}")
