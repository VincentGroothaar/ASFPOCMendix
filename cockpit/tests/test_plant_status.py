"""Tests for plant_status.plant_result: snapshot rows in, shortage statuses out (#27)."""

from datetime import date
from decimal import Decimal

import pytest
from django.utils import timezone

from cockpit.models import BufferChange, Component, ProductionOrder, Stock
from cockpit.services.plant_status import plant_result
from cockpit.services.shortage import Status

TODAY = date(2026, 11, 3)


def add_order(number, start, components, plant="AUC1", is_active=True):
    """Store an order with (item, material, required, unit) component lines."""
    order = ProductionOrder.objects.create(
        number=number,
        plant=plant,
        material="FG-1",
        quantity=Decimal("1"),
        unit="PC",
        start_date=start,
        is_active=is_active,
        synced_at=timezone.now(),
    )
    for item, material, required, unit in components:
        Component.objects.create(
            order=order,
            item=item,
            material=material,
            required_quantity=Decimal(required),
            withdrawn_quantity=Decimal("0"),
            unit=unit,
        )
    return order


def add_stock(material, quantity, unit="PC", plant="AUC1"):
    Stock.objects.create(
        plant=plant, material=material, quantity=Decimal(quantity), unit=unit,
        synced_at=timezone.now(),
    )  # fmt: skip


@pytest.mark.django_db
def test_maps_the_snapshot_and_allocates_by_start_date():
    add_order("1000002", date(2026, 11, 5), [("0001", "RM-1", "60", "PC")])
    add_order("1000001", date(2026, 11, 4), [("0001", "RM-1", "60", "PC")])
    add_stock("RM-1", "100")

    result = plant_result("AUC1", TODAY)

    assert list(result.orders) == ["1000001", "1000002"]
    assert result.component("1000001", "0001").status is Status.COVERED
    assert result.component("1000002", "0001").status is Status.SHORT
    assert result.component("1000002", "0001").shortage == Decimal("20")


@pytest.mark.django_db
def test_only_active_orders_of_the_plant_count():
    add_order("1000001", date(2026, 11, 4), [("0001", "RM-1", "60", "PC")], is_active=False)
    add_order("2000001", date(2026, 11, 4), [("0001", "RM-1", "60", "PC")], plant="USC1")
    add_order("1000002", date(2026, 11, 5), [("0001", "RM-1", "60", "PC")])
    add_stock("RM-1", "60")

    result = plant_result("AUC1", TODAY)

    assert list(result.orders) == ["1000002"]
    assert result.component("1000002", "0001").available == Decimal("60")


@pytest.mark.django_db
def test_uses_the_current_buffer(make_user):
    BufferChange.objects.create(value=Decimal("25"), changed_by=make_user("Manager"))
    add_order("1000001", date(2026, 11, 4), [("0001", "RM-1", "100", "PC")])
    add_stock("RM-1", "120")

    result = plant_result("AUC1", TODAY)

    assert result.buffer_percent == Decimal("25")
    assert result.component("1000001", "0001").status is Status.LOW_COVER
