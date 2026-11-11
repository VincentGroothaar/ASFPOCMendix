"""Domain model of the cockpit (the Mendix domain model), spec in issue #21.

Two groups of models:
- The snapshot of SAP data per plant (PlantSnapshot, ProductionOrder, Component, Stock).
  Only the sync service (#24) writes these; the app never edits them.
- The app's own records (Requisition, BufferChange). Postgres is their source of truth.

Every quantity is a Decimal with 3 decimals, as in SAP (INV-5).
"""

from typing import Any

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

# Field sizes for SAP codes, so every model uses the same ones.
PLANT_LENGTH = 4
ORDER_NUMBER_LENGTH = 12
MATERIAL_LENGTH = 40
DESCRIPTION_LENGTH = 40
UNIT_LENGTH = 3
ITEM_LENGTH = 4


def quantity_field(**options: Any) -> models.DecimalField:
    """A quantity column: 15 digits, 3 of them decimals (decision 5 on #21)."""
    return models.DecimalField(max_digits=15, decimal_places=3, **options)


# --- Snapshot (from SAP) ------------------------------------------------------------------------


class PlantSnapshot(models.Model):
    """When a plant was last loaded from SAP, and the last sync error (REQ-1)."""

    plant = models.CharField(max_length=PLANT_LENGTH, unique=True)
    synced_at = models.DateTimeField(null=True, blank=True)  # empty = never synced
    last_sync_error = models.TextField(blank=True)
    last_sync_error_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return self.plant


class ProductionOrder(models.Model):
    """A released production order. Never deleted; is_active is False once SAP drops it."""

    number = models.CharField(max_length=ORDER_NUMBER_LENGTH, unique=True)
    plant = models.CharField(max_length=PLANT_LENGTH)
    material = models.CharField(max_length=MATERIAL_LENGTH)
    description = models.CharField(max_length=DESCRIPTION_LENGTH, blank=True)
    quantity = quantity_field()
    unit = models.CharField(max_length=UNIT_LENGTH)
    start_date = models.DateField()
    is_active = models.BooleanField(default=True)
    synced_at = models.DateTimeField()

    class Meta:
        indexes = [
            models.Index(
                fields=["plant", "is_active", "start_date"], name="order_plant_active_start"
            )
        ]

    def __str__(self) -> str:
        return self.number


class Component(models.Model):
    """One component line of an order. Quantities are in `unit` (the order's unit)."""

    order = models.ForeignKey(ProductionOrder, on_delete=models.CASCADE, related_name="components")
    item = models.CharField(max_length=ITEM_LENGTH)
    material = models.CharField(max_length=MATERIAL_LENGTH)
    description = models.CharField(max_length=DESCRIPTION_LENGTH, blank=True)
    required_quantity = quantity_field()
    withdrawn_quantity = quantity_field()
    unit = models.CharField(max_length=UNIT_LENGTH)

    class Meta:
        ordering = ["item"]
        constraints = [
            models.UniqueConstraint(fields=["order", "item"], name="one_component_per_item")
        ]

    def __str__(self) -> str:
        return f"{self.order.number}/{self.item}"


class Stock(models.Model):
    """Unrestricted-use stock of a material in a plant, summed over storage locations."""

    plant = models.CharField(max_length=PLANT_LENGTH)
    material = models.CharField(max_length=MATERIAL_LENGTH)
    quantity = quantity_field()
    unit = models.CharField(max_length=UNIT_LENGTH)
    synced_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["plant", "material"], name="one_stock_per_material")
        ]

    def __str__(self) -> str:
        return f"{self.plant}/{self.material}"


# --- Owned by the app ---------------------------------------------------------------------------


class Requisition(models.Model):
    """One attempt to request a purchase requisition for one order and material (REQ-5).

    A retry or a new request after a rejection is a new row. At most one row per order and
    material may be awaiting approval or sent (INV-7); failed and rejected rows never block.
    """

    class Status(models.TextChoices):
        AWAITING_APPROVAL = "awaiting_approval", "Awaiting approval"
        SENT = "sent", "PR sent"
        FAILED = "failed", "PR failed"
        REJECTED = "rejected", "Rejected"

    order = models.ForeignKey(
        ProductionOrder, on_delete=models.PROTECT, related_name="requisitions"
    )
    material = models.CharField(max_length=MATERIAL_LENGTH)
    items = models.CharField(max_length=200)  # e.g. "0010" or "0010, 0020", at request time
    quantity_entered = quantity_field()  # in the order's unit
    unit_entered = models.CharField(max_length=UNIT_LENGTH)
    quantity_sent = quantity_field()  # in the stock unit
    unit_sent = models.CharField(max_length=UNIT_LENGTH)
    shortage_at_request = quantity_field(null=True, blank=True)  # in the order's unit
    delivery_date = models.DateField()
    status = models.CharField(max_length=20, choices=Status.choices)
    pr_number = models.CharField(max_length=20, blank=True)
    payload = models.JSONField(null=True, blank=True)
    response = models.JSONField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="requisitions"
    )
    created_at = models.DateTimeField(default=timezone.now)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="decided_requisitions",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    reject_reason = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["order", "material"],
                # Open = awaiting approval or sent; failed and rejected never block.
                condition=Q(status__in=["awaiting_approval", "sent"]),
                name="one_open_requisition_per_order_material",
            )
        ]

    @property
    def reference(self) -> str:
        """The app reference shown on screen, e.g. REQ-16 (not stored, decision B-1 on #21)."""
        return f"REQ-{self.pk}"

    def __str__(self) -> str:
        return self.reference


class BufferChange(models.Model):
    """One change of the cover buffer. The newest row is the current buffer (#21)."""

    value = models.DecimalField(max_digits=5, decimal_places=2)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="buffer_changes"
    )
    changed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(value__gte=0) & Q(value__lte=100), name="buffer_between_0_and_100"
            )
        ]

    def __str__(self) -> str:
        return f"{self.value}%"
