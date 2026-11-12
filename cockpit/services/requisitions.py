"""Purchase requisitions: prefill, rules, sending and storing every attempt (REQ-5, #27).

All requisition rules live here; the view only calls `prepare` and `create`.
In Mendix terms these are the microflows behind the "Request" button.

The order of `create` follows ARCHITECTURE.md, "Create requisition":
role check, eligibility, quantity, then one transaction that inserts the row as `sent`
(the database constraint blocks a second open requisition, INV-7), sends it to the mock and
stores the outcome. After the commit, a successful send re-syncs the plant.
"""

import logging
import re
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_CEILING, Decimal

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.utils import timezone

from cockpit.models import ProductionOrder, Requisition
from cockpit.services import plant_status, units
from cockpit.services.roles import Action, can
from cockpit.services.shortage import ComponentResult, Status
from cockpit.services.sync import sync_plant
from sap.requisitions import build_payload, create_requisition

logger = logging.getLogger(__name__)

# Quantities are entered and sent with at most 3 decimals (REQ-5; SAP RequestedQuantity Scale 3).
DECIMALS = Decimal("0.001")
# A quantity as a planner types it: ASCII digits, optionally a point and more digits (#68).
PLAIN_NUMBER = re.compile(r"[0-9]+(\.[0-9]+)?", re.ASCII)
# SAP's RequestedQuantity is Precision 13, Scale 3: at most 10 digits before the point.
MAX_SENT = Decimal("9999999999.999")
# The database constraint that allows one open requisition per order and material (INV-7).
OPEN_CONSTRAINT = "one_open_requisition_per_order_material"
OPEN_STATUSES = [Requisition.Status.SENT, Requisition.Status.AWAITING_APPROVAL]
REQUESTABLE = {Status.SHORT, Status.LOW_COVER}
# Requisition.items is a CharField(200); a longer list is shortened (decision on #68).
MAX_ITEMS_LENGTH = 200
# Longest error text stored with an attempt; SAP's own messages are far shorter.
MAX_ERROR_LENGTH = 2000


class RequisitionRefused(Exception):
    """A request the cockpit refuses before anything is stored or sent.

    `reason` is one of: "unknown" (no such order or material), "not_requestable",
    "invalid_quantity" or "duplicate". `message` is shown to the user. For a duplicate,
    `existing` is the open requisition that blocks it (or None if it could not be found).
    """

    def __init__(self, reason: str, message: str, existing: Requisition | None = None) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.existing = existing


@dataclass(frozen=True)
class Prefill:
    """What the confirm step shows for one order and material.

    `shortage`, `quantity` and `unit` are in the order unit; `quantity_sent` and `stock_unit`
    are what would be sent to SAP for `quantity`.
    """

    order: str
    material: str
    description: str
    plant: str
    items: tuple[str, ...]
    shortage: Decimal
    quantity: Decimal
    unit: str
    quantity_sent: Decimal
    stock_unit: str
    delivery_date: date
    low_cover: bool
    cover_percent: Decimal  # 100 + buffer, for the "To 110% cover" label (ui-spec 4.2)


def prepare(order_number: str, material: str, today: date | None = None) -> Prefill:
    """Work out the prefilled requisition for one order and material.

    The prefill is the sum of the material's Short and Low cover lines in this order: the
    shortage of a Short line, and the amount that brings a Low cover line up to
    (100 + buffer)% of its open requirement. Lines in another unit are converted to the unit of
    the first such line. The sum is rounded up to 3 decimals.

    Raises RequisitionRefused ("unknown" or "not_requestable").
    """
    today = today or timezone.localdate()
    order = ProductionOrder.objects.filter(number=order_number).first()
    if order is None:
        raise RequisitionRefused("unknown", "This order does not exist.")
    if not order.is_active:
        raise RequisitionRefused(
            "not_requestable", "This order is no longer released in SAP, so it cannot be requested."
        )
    result = plant_status.plant_result(order.plant, today)
    lines = [line for line in result.orders[order.number].components if line.material == material]
    if not lines:
        raise RequisitionRefused("unknown", "This material is not a component of this order.")
    eligible = [line for line in lines if line.status in REQUESTABLE]
    if not eligible:
        raise RequisitionRefused(
            "not_requestable",
            "This material is not short or low on cover in this order, so it cannot be requested.",
        )

    unit = eligible[0].unit
    stock_unit = eligible[0].stock_unit
    buffer_percent = result.buffer_percent
    quantity = sum(
        (units.convert(_line_amount(line, buffer_percent), line.unit, unit) for line in eligible),
        Decimal(0),
    )
    shortage = sum(
        (units.convert(line.shortage or Decimal(0), line.unit, unit) for line in eligible),
        Decimal(0),
    )
    quantity = _round_up(quantity)
    descriptions = order.components.filter(material=material).exclude(description="")
    first_description = descriptions.values_list("description", flat=True).first()
    return Prefill(
        order=order.number,
        material=material,
        description=first_description or "",
        plant=order.plant,
        items=tuple(line.item for line in lines),
        shortage=_round_up(shortage),
        quantity=quantity,
        unit=unit,
        quantity_sent=to_stock_unit(quantity, unit, stock_unit),
        stock_unit=stock_unit,
        delivery_date=max(order.start_date, today),
        low_cover=all(line.status is Status.LOW_COVER for line in eligible),
        cover_percent=Decimal(100) + buffer_percent,
    )


def validate_quantity(raw: str) -> Decimal:
    """Read the quantity a planner typed: greater than 0, at most 3 decimals (REQ-5).

    Only plain digits with an optional decimal point are accepted (12, 12.5, 0.001): no sign,
    exponent, underscore, comma or other scripts. Decimals are counted on the text, so nothing
    is rounded first; trailing zeros don't count ("1.2000" is 1.2). Raises RequisitionRefused
    ("invalid_quantity") with a message for the form.
    """
    text = (raw or "").strip()
    if not text:
        raise RequisitionRefused("invalid_quantity", "Enter a quantity.")
    if not PLAIN_NUMBER.fullmatch(text):
        raise RequisitionRefused("invalid_quantity", "Enter a number, for example 12.5.")
    whole, _, fraction = text.partition(".")
    if len(fraction.rstrip("0")) > 3:
        raise RequisitionRefused("invalid_quantity", "Use at most 3 decimals.")
    if len(whole.lstrip("0")) > 12:
        raise RequisitionRefused("invalid_quantity", "This quantity is too large.")
    # Exact: at most 12 digits before and 3 after the point, so quantize never rounds.
    quantity = Decimal(whole + "." + (fraction or "0")).quantize(DECIMALS)
    if quantity <= 0:
        raise RequisitionRefused("invalid_quantity", "Enter a quantity greater than 0.")
    return quantity


def to_stock_unit(quantity: Decimal, unit: str, stock_unit: str) -> Decimal:
    """The quantity to send to SAP: converted to the stock unit, rounded up to 3 decimals.

    Raises RequisitionRefused ("invalid_quantity") when SAP could not take the number.
    """
    sent = _round_up(units.convert(quantity, unit, stock_unit))
    if sent > MAX_SENT:
        raise RequisitionRefused(
            "invalid_quantity", f"This quantity is too large to send to SAP in {stock_unit}."
        )
    return sent


def create(
    user, order_number: str, material: str, raw_quantity: str, today: date | None = None
) -> Requisition:
    """Create one requisition: check, store, send to the mock and store the outcome.

    Returns the stored requisition with status `sent` (with a PR number) or `failed` (with an
    error message). Must not be called inside a database transaction, so the re-sync after a
    successful send sees the committed requisition.

    Raises:
        PermissionDenied: the user's role may not create requisitions (INV-1).
        RequisitionRefused: unknown, not requestable, invalid quantity, or a duplicate (INV-7).
    """
    if not can(user, Action.CREATE_REQUISITION):
        raise PermissionDenied
    today = today or timezone.localdate()
    prefill = prepare(order_number, material, today)
    quantity = validate_quantity(raw_quantity)
    quantity_sent = to_stock_unit(quantity, prefill.unit, prefill.stock_unit)
    payload = build_payload(
        material, prefill.plant, quantity_sent, prefill.stock_unit, prefill.delivery_date
    )
    order = ProductionOrder.objects.get(number=order_number)

    with transaction.atomic(durable=True):
        requisition = _insert(order, prefill, quantity, quantity_sent, payload, user)
        result = create_requisition(payload)
        requisition.response = _without_nul(result.response)
        if result.ok:
            requisition.pr_number = result.pr_number
            requisition.sent_at = timezone.now()
        else:
            requisition.status = Requisition.Status.FAILED
            requisition.error_message = _without_nul(result.error_message)[:MAX_ERROR_LENGTH]
        requisition.save()

    if requisition.status == Requisition.Status.SENT:
        _resync(prefill.plant, requisition)
    return requisition


def _insert(
    order: ProductionOrder,
    prefill: Prefill,
    quantity: Decimal,
    quantity_sent: Decimal,
    payload: dict,
    user,
) -> Requisition:
    """Store the attempt as `sent`, before sending. A second open one fails the constraint."""
    try:
        # Own savepoint: after a constraint error the outer transaction stays usable.
        with transaction.atomic():
            return Requisition.objects.create(
                order=order,
                material=prefill.material,
                items=_items_text(prefill.items),
                quantity_entered=quantity,
                unit_entered=prefill.unit,
                quantity_sent=quantity_sent,
                unit_sent=prefill.stock_unit,
                shortage_at_request=prefill.shortage,
                delivery_date=prefill.delivery_date,
                status=Requisition.Status.SENT,
                payload=payload,
                created_by=user,
            )
    except IntegrityError as error:
        if _constraint_name(error) != OPEN_CONSTRAINT:
            raise
    existing = Requisition.objects.filter(
        order=order, material=prefill.material, status__in=OPEN_STATUSES
    ).first()
    if existing is None:
        message = "A requisition for this order and material is already open."
    else:
        message = (
            f"A requisition for this order and material is already open ({existing.reference})."
        )
    raise RequisitionRefused("duplicate", message, existing)


def _resync(plant: str, requisition: Requisition) -> None:
    """Re-sync the plant after a sent requisition. Never changes the requisition's outcome."""
    try:
        sync_plant(plant)
    except Exception:
        # SAP problems already come back as a failed SyncState; this is a bug or a database
        # error. The PR is sent and stored, so the planner still sees "PR sent".
        logger.exception("Re-sync of plant %s after %s failed", plant, requisition.reference)


def _items_text(items: tuple[str, ...]) -> str:
    """The item numbers as stored: "0001, 0002", shortened with "… (+n more)" to fit 200."""
    text = ", ".join(items)
    if len(text) <= MAX_ITEMS_LENGTH:
        return text
    for count in range(len(items) - 1, 0, -1):
        text = f"{', '.join(items[:count])} … (+{len(items) - count} more)"
        if len(text) <= MAX_ITEMS_LENGTH:
            return text
    return f"… ({len(items)} items)"


def _line_amount(line: ComponentResult, buffer_percent: Decimal) -> Decimal:
    """The amount one Short or Low cover line asks for, in the line's own unit."""
    available = line.available or Decimal(0)
    if line.status is Status.SHORT:
        return line.shortage or Decimal(0)
    target = (Decimal(100) + buffer_percent) / Decimal(100) * line.open_requirement
    return max(Decimal(0), target - available)


def _round_up(value: Decimal) -> Decimal:
    """Round up (towards +infinity) to 3 decimals, so the cockpit never orders less."""
    return value.quantize(DECIMALS, rounding=ROUND_CEILING)


def _constraint_name(error: IntegrityError) -> str:
    """The name of the database constraint behind an IntegrityError (Postgres, via psycopg)."""
    diag = getattr(error.__cause__, "diag", None)
    return getattr(diag, "constraint_name", None) or ""


def _without_nul(value):
    """The value with NUL characters removed from every text in it (Postgres can't store them)."""
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, dict):
        return {_without_nul(key): _without_nul(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_without_nul(item) for item in value]
    return value
