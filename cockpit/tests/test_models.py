"""Tests for the data model and the buffer service (issue #21, criteria M-2 to M-6)."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.db import IntegrityError, models, transaction
from django.db.models import ProtectedError
from django.utils import timezone

from cockpit.models import (
    BufferChange,
    Component,
    PlantSnapshot,
    ProductionOrder,
    Requisition,
    Stock,
)
from cockpit.services.buffer import DEFAULT_BUFFER, current_buffer, last_change

pytestmark = pytest.mark.django_db

Status = Requisition.Status


# --- Helpers ------------------------------------------------------------------------------------


@pytest.fixture
def planner() -> User:
    return User.objects.create_user("planner", password="not-used")


def make_order(number: str = "1000001") -> ProductionOrder:
    """A minimal order in plant AUC1."""
    return ProductionOrder.objects.create(
        number=number,
        plant="AUC1",
        material="FG-1",
        quantity=Decimal("10"),
        unit="PC",
        start_date=date(2026, 11, 4),
        synced_at=timezone.now(),
    )


def make_requisition(order: ProductionOrder, material: str, status: str, user: User) -> Requisition:
    """A requisition with fixed quantities; only order, material and status vary."""
    return Requisition.objects.create(
        order=order,
        material=material,
        items="0010",
        quantity_entered=Decimal("5"),
        unit_entered="PC",
        quantity_sent=Decimal("5"),
        unit_sent="PC",
        delivery_date=date(2026, 11, 4),
        status=status,
        created_by=user,
    )


# --- M-2: duplicate guard (INV-7) ---------------------------------------------------------------

OPEN = [Status.AWAITING_APPROVAL, Status.SENT]


@pytest.mark.parametrize("first", OPEN)
@pytest.mark.parametrize("second", OPEN)
def test_second_open_requisition_for_same_order_and_material_is_refused(
    planner, first, second
) -> None:
    order = make_order()
    make_requisition(order, "RM-1", first, planner)

    with pytest.raises(IntegrityError), transaction.atomic():
        make_requisition(order, "RM-1", second, planner)


def test_failed_and_rejected_requisitions_do_not_block(planner) -> None:
    order = make_order()
    make_requisition(order, "RM-1", Status.FAILED, planner)
    make_requisition(order, "RM-1", Status.FAILED, planner)
    make_requisition(order, "RM-1", Status.REJECTED, planner)

    make_requisition(order, "RM-1", Status.SENT, planner)

    assert Requisition.objects.count() == 4


def test_open_requisitions_for_other_materials_or_orders_do_not_block(planner) -> None:
    order = make_order("1000001")
    other_order = make_order("1000002")
    make_requisition(order, "RM-1", Status.SENT, planner)

    make_requisition(order, "RM-2", Status.SENT, planner)
    make_requisition(other_order, "RM-1", Status.AWAITING_APPROVAL, planner)

    assert Requisition.objects.count() == 3


def test_a_rejected_request_frees_the_order_and_material_again(planner) -> None:
    order = make_order()
    waiting = make_requisition(order, "RM-1", Status.AWAITING_APPROVAL, planner)
    waiting.status = Status.REJECTED
    waiting.save()

    make_requisition(order, "RM-1", Status.AWAITING_APPROVAL, planner)

    assert Requisition.objects.filter(status=Status.AWAITING_APPROVAL).count() == 1


# --- M-3: REQ-n reference -----------------------------------------------------------------------


@pytest.mark.parametrize(("pk", "expected"), [(7, "REQ-7"), (16, "REQ-16"), (12345, "REQ-12345")])
def test_reference_is_req_and_the_unpadded_id(pk, expected) -> None:
    assert Requisition(pk=pk).reference == expected


def test_stored_requisitions_get_increasing_references(planner) -> None:
    order = make_order()
    first = make_requisition(order, "RM-1", Status.FAILED, planner)
    second = make_requisition(order, "RM-1", Status.FAILED, planner)

    assert first.reference == f"REQ-{first.pk}"
    assert second.pk > first.pk


# --- M-4: inactive orders keep their requisitions -----------------------------------------------


def test_inactive_order_keeps_its_requisitions(planner) -> None:
    order = make_order()
    requisition = make_requisition(order, "RM-1", Status.SENT, planner)

    order.is_active = False
    order.save()

    requisition.refresh_from_db()
    assert requisition.order == order
    assert list(order.requisitions.all()) == [requisition]


def test_order_with_requisitions_cannot_be_deleted(planner) -> None:
    order = make_order()
    make_requisition(order, "RM-1", Status.SENT, planner)

    with pytest.raises(ProtectedError):
        order.delete()


def test_deleting_an_order_without_requisitions_deletes_its_components() -> None:
    order = make_order()
    Component.objects.create(
        order=order,
        item="0010",
        material="RM-1",
        required_quantity=Decimal("2"),
        withdrawn_quantity=Decimal("0"),
        unit="PC",
    )

    order.delete()

    assert Component.objects.count() == 0


# --- M-5: cover buffer --------------------------------------------------------------------------


def test_buffer_is_10_when_never_changed() -> None:
    assert current_buffer() == Decimal("10")
    assert DEFAULT_BUFFER == Decimal("10")
    assert last_change() is None


def test_buffer_is_the_newest_change(planner) -> None:
    now = timezone.now()
    BufferChange.objects.create(value=Decimal("12.5"), changed_by=planner, changed_at=now)
    BufferChange.objects.create(
        value=Decimal("20"), changed_by=planner, changed_at=now - timedelta(hours=1)
    )

    assert current_buffer() == Decimal("12.50")
    assert last_change().changed_by == planner


@pytest.mark.parametrize("value", ["0", "100"])
def test_buffer_accepts_the_limits(planner, value) -> None:
    BufferChange.objects.create(value=Decimal(value), changed_by=planner)

    assert current_buffer() == Decimal(value)


@pytest.mark.parametrize("value", ["-1", "100.01"])
def test_buffer_outside_0_to_100_is_refused_by_the_database(planner, value) -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        BufferChange.objects.create(value=Decimal(value), changed_by=planner)


# --- M-6: Decimal quantities (INV-5) ------------------------------------------------------------

QUANTITY_FIELDS = [
    (ProductionOrder, "quantity"),
    (Component, "required_quantity"),
    (Component, "withdrawn_quantity"),
    (Stock, "quantity"),
    (Requisition, "quantity_entered"),
    (Requisition, "quantity_sent"),
    (Requisition, "shortage_at_request"),
]


@pytest.mark.parametrize(("model", "name"), QUANTITY_FIELDS)
def test_quantity_fields_are_decimals_with_3_decimals(model, name) -> None:
    field = model._meta.get_field(name)

    assert isinstance(field, models.DecimalField)
    assert field.decimal_places == 3
    assert field.max_digits == 15


def test_quantity_round_trips_exactly() -> None:
    Stock.objects.create(
        plant="AUC1",
        material="RM-1",
        quantity=Decimal("109.999"),
        unit="KG",
        synced_at=timezone.now(),
    )

    stored = Stock.objects.get().quantity
    assert isinstance(stored, Decimal)
    assert stored == Decimal("109.999")


def test_one_stock_row_per_plant_and_material() -> None:
    Stock.objects.create(
        plant="AUC1", material="RM-1", quantity=1, unit="KG", synced_at=timezone.now()
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        Stock.objects.create(
            plant="AUC1", material="RM-1", quantity=2, unit="KG", synced_at=timezone.now()
        )


def test_plant_snapshot_starts_never_synced() -> None:
    snapshot = PlantSnapshot.objects.create(plant="AUC1")

    assert snapshot.synced_at is None
    assert snapshot.last_sync_error == ""
