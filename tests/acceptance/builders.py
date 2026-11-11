"""The only place where the acceptance tests touch the app's internals (issue #15).

The spec fixes URLs, service functions and on-screen copy, and the tests use those directly.
It leaves some things to the implementation: model fields, form field names, and the input
and output types of `shortage.calculate`. Every such detail goes through a function here.

Rules for implementing PRs:
- Fill in or adjust these functions as a **thin translation** to the real code.
- Never change a test's assertions to make it pass. If a test is wrong, fix the spec first.
- A function that still raises NotImplementedError keeps its tests failing (strict xfail).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import override_settings

from tests.acceptance.support import Order, Stock

ROLES = ("Viewer", "Planner", "Manager", "Admin")

# The status names shown on screen (ui-spec 3.1), used for every status in these tests.
SHORT = "Short"
LOW_COVER = "Low cover"
COVERED = "Covered"
UNIT_MISMATCH = "Unit mismatch"
ISSUED = "Issued"

# --- Users --------------------------------------------------------------------------------------


def make_user(role: str, username: str | None = None) -> User:
    """Create a user with one role (ARCHITECTURE.md: one Django group per role).

    Group membership is all a role needs (#22): Admin does not need staff status, because the
    admin site checks the role itself. This matches what `create_test_users` sets up.
    """
    assert role in ROLES, f"Unknown role {role}"
    user = User.objects.create_user(username or role.lower(), password="not-used")
    group, _ = Group.objects.get_or_create(name=role)
    user.groups.add(group)
    return user


# --- Settings -----------------------------------------------------------------------------------


def plants_setting(plants: list[str]):
    """Override COCKPIT_PLANTS for a test (a context manager)."""
    return override_settings(COCKPIT_PLANTS=plants)


# --- Forms --------------------------------------------------------------------------------------


def requisition_form(quantity: str) -> dict[str, str]:
    """POST data for the confirm step of a requisition (field "Quantity", ui-spec 4.2)."""
    return {"quantity": quantity}


def reject_form(reason: str = "") -> dict[str, str]:
    """POST data for rejecting a requisition ("Reason (optional)", ui-spec 4.4)."""
    return {"reason": reason}


def buffer_form(value: str) -> dict[str, str]:
    """POST data for saving the cover buffer on /settings/ ("New value (%)", ui-spec 4.6)."""
    return {"buffer": value}


# --- Requisitions -------------------------------------------------------------------------------

AWAITING_APPROVAL = "awaiting_approval"
SENT = "sent"
FAILED = "failed"
REJECTED = "rejected"


@dataclass
class RequisitionRecord:
    """A stored requisition, in plain values (ARCHITECTURE.md, Data model)."""

    id: int
    order: str
    material: str
    status: str  # one of AWAITING_APPROVAL, SENT, FAILED, REJECTED
    pr_number: str
    quantity_sent: Decimal | None
    unit_sent: str
    delivery_date: date | None
    created_by: str
    reject_reason: str


def requisitions() -> list[RequisitionRecord]:
    """All stored requisitions, oldest first. #21 / #27 fill this in."""
    raise NotImplementedError("Requisition model not built yet (#21)")


def store_requisition(order: str, material: str, status: str, created_by: User) -> None:
    """Write a requisition straight to the database, bypassing the service (only for INV-7).

    The order must already be in the snapshot (sync first). #21 fills this in.
    """
    raise NotImplementedError("Requisition model not built yet (#21)")


# --- Status calculation -------------------------------------------------------------------------


@dataclass
class ComponentOutcome:
    """The calculated result for one component line, in the component's (order's) unit."""

    status: str  # SHORT, LOW_COVER, COVERED, UNIT_MISMATCH or ISSUED
    available: Decimal | None
    shortage: Decimal | None


@dataclass
class OrderOutcome:
    status: str  # worst component status; SHORT, LOW_COVER or COVERED
    unit_mismatch: bool  # the warning badge


@dataclass
class PlantOutcome:
    components: dict[tuple[str, str], ComponentOutcome]  # by (order number, item)
    orders: dict[str, OrderOutcome]  # by order number

    def component(self, order: str, item: str = "0001") -> ComponentOutcome:
        return self.components[(order, item)]


def calculate(
    orders: list[Order], stock: list[Stock], buffer: Decimal = Decimal("10")
) -> PlantOutcome:
    """Run `cockpit.services.shortage.calculate` on plain test data (spec.md, Modules).

    Translates `orders`, `stock` (including safety stock) and the buffer into the input types
    of `calculate`, and its PlantResult back into a PlantOutcome. #20 fills this in.
    """
    raise NotImplementedError("shortage.calculate not built yet (#20)")
