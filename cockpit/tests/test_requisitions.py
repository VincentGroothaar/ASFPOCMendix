"""Tests for the requisition service (#27): prefill, rules, sending and storing attempts.

The write client is replaced by a fake, so no HTTP is sent. The snapshot is stored directly.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction

from cockpit.models import Requisition
from cockpit.services import requisitions
from cockpit.services.requisitions import (
    RequisitionRefused,
    create,
    prepare,
    to_stock_unit,
    validate_quantity,
)
from cockpit.tests.test_plant_status import add_order, add_stock
from sap.requisitions import NOT_ACCEPTED, RequisitionResult

TODAY = date(2026, 11, 3)
START = date(2026, 11, 10)


@pytest.fixture
def sent_to(monkeypatch):
    """Replace the write client: records payloads and answers with `answer` (a PR by default)."""

    class FakeClient:
        def __init__(self) -> None:
            self.payloads: list[dict] = []
            self.answer = RequisitionResult("10000000", "", {"status": 201})

        def __call__(self, payload: dict) -> RequisitionResult:
            self.payloads.append(payload)
            return self.answer

    fake = FakeClient()
    monkeypatch.setattr(requisitions, "create_requisition", fake)
    return fake


@pytest.fixture
def resyncs(monkeypatch):
    """Replace sync_plant: records the plants and whether a transaction was open."""
    calls: list[tuple[str, bool]] = []

    def fake_sync(plant: str) -> None:
        calls.append((plant, transaction.get_connection().in_atomic_block))

    monkeypatch.setattr(requisitions, "sync_plant", fake_sync)
    return calls


@pytest.fixture
def planner(make_user) -> User:
    return make_user("Planner")


def mixed_order():
    """RM-SHORT needs 100 with 70 in stock (short 30); RM-LOW needs 100 with 104 (6 to 110%)."""
    add_order(
        "1000001",
        START,
        [
            ("0001", "RM-SHORT", "100", "PC"),
            ("0002", "RM-LOW", "100", "PC"),
            ("0003", "RM-COVER", "100", "PC"),
        ],
    )
    add_stock("RM-SHORT", "70")
    add_stock("RM-LOW", "104")
    add_stock("RM-COVER", "200")


# --- prepare ------------------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("material", "quantity", "low_cover"), [("RM-SHORT", "30", False), ("RM-LOW", "6", True)]
)
def test_prefill_for_short_and_low_cover(material, quantity, low_cover):
    mixed_order()

    prefill = prepare("1000001", material, TODAY)

    assert prefill.quantity == Decimal(quantity)
    assert prefill.low_cover is low_cover
    assert prefill.unit == prefill.stock_unit == "PC"
    assert prefill.delivery_date == START
    assert prefill.cover_percent == Decimal("110")


@pytest.mark.django_db
def test_combined_lines_add_up_and_list_every_item():
    """R-1: shortages 10 + 5 on two lines of one material prefill 15."""
    add_order(
        "1000001", START, [("0001", "RM-1", "50", "PC"), ("0002", "RM-1", "5", "PC")]
    )  # stock 40: line 1 short 10, line 2 sees 0, short 5
    add_stock("RM-1", "40")

    prefill = prepare("1000001", "RM-1", TODAY)

    assert prefill.quantity == Decimal("15")
    assert prefill.shortage == Decimal("15")
    assert prefill.items == ("0001", "0002")


@pytest.mark.django_db
def test_mixed_units_convert_to_the_first_eligible_line():
    """R-1: 0.5 KG short + 200 G short prefill 0.7 KG."""
    add_order("1000001", START, [("0001", "RM-1", "0.5", "KG"), ("0002", "RM-1", "200", "G")])

    prefill = prepare("1000001", "RM-1", TODAY)

    assert (prefill.quantity, prefill.unit) == (Decimal("0.7"), "KG")


@pytest.mark.django_db
def test_lines_that_do_not_count_are_skipped_even_in_another_unit():
    """R-1: an Issued PC line plus a Short KG line prefills the KG shortage."""
    order = add_order("1000001", START, [("0001", "RM-1", "3", "PC"), ("0002", "RM-1", "2", "KG")])
    issued = order.components.get(item="0001")
    issued.withdrawn_quantity = Decimal("3")
    issued.save()
    add_stock("RM-1", "0.5", unit="KG")

    prefill = prepare("1000001", "RM-1", TODAY)

    assert (prefill.quantity, prefill.unit) == (Decimal("1.5"), "KG")
    assert prefill.items == ("0001", "0002")


@pytest.mark.django_db
def test_prefill_rounds_up_to_3_decimals(make_user):
    """AC-22: requirement 0.333, available 0.35, buffer 12.25 → 0.0237925 → 0.024."""
    from cockpit.models import BufferChange

    BufferChange.objects.create(value=Decimal("12.25"), changed_by=make_user("Manager"))
    add_order("1000001", START, [("0001", "RM-1", "0.333", "KG")])
    add_stock("RM-1", "0.35", unit="KG")

    assert prepare("1000001", "RM-1", TODAY).quantity == Decimal("0.024")


@pytest.mark.django_db
def test_delivery_date_is_today_when_the_start_has_passed():
    add_order("1000001", date(2026, 10, 30), [("0001", "RM-1", "5", "PC")])

    assert prepare("1000001", "RM-1", TODAY).delivery_date == TODAY


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("order", "material", "reason"),
    [
        ("9999999", "RM-SHORT", "unknown"),
        ("1000001", "RM-NOPE", "unknown"),
        ("1000001", "RM-COVER", "not_requestable"),
    ],
)
def test_prepare_refuses(order, material, reason):
    mixed_order()

    with pytest.raises(RequisitionRefused) as refused:
        prepare(order, material, TODAY)

    assert refused.value.reason == reason


@pytest.mark.django_db
def test_an_inactive_order_cannot_be_requested():
    add_order("1000001", START, [("0001", "RM-1", "5", "PC")], is_active=False)

    with pytest.raises(RequisitionRefused) as refused:
        prepare("1000001", "RM-1", TODAY)

    assert refused.value.reason == "not_requestable"


@pytest.mark.django_db
def test_a_unit_mismatch_cannot_be_requested():
    add_order("1000001", START, [("0001", "RM-1", "5", "PC")])
    add_stock("RM-1", "1", unit="KG")

    with pytest.raises(RequisitionRefused) as refused:
        prepare("1000001", "RM-1", TODAY)

    assert refused.value.reason == "not_requestable"


# --- validate_quantity and to_stock_unit --------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"), [("30", "30"), (" 12.5 ", "12.5"), ("0.001", "0.001"), ("1.2000", "1.2")]
)
def test_valid_quantities(raw, expected):
    assert validate_quantity(raw) == Decimal(expected)


@pytest.mark.parametrize(
    "raw", ["", "  ", "0", "-5", "abc", "1.2345", "0.0001", "NaN", "Infinity", "1" * 13]
)
def test_invalid_quantities_are_refused(raw):
    with pytest.raises(RequisitionRefused) as refused:
        validate_quantity(raw)

    assert refused.value.reason == "invalid_quantity"
    assert refused.value.message


def test_stock_unit_quantity_is_rounded_up():
    """R-2: 0.5 G is 0.0005 KG, which is sent as 0.001 KG."""
    assert to_stock_unit(Decimal("0.5"), "G", "KG") == Decimal("0.001")
    assert to_stock_unit(Decimal("0.5"), "KG", "G") == Decimal("500")


def test_stock_unit_quantity_above_the_sap_limit_is_refused():
    """R-2: SAP takes at most 9,999,999,999.999."""
    assert to_stock_unit(Decimal("9999999.999"), "KG", "G") == Decimal("9999999999")
    with pytest.raises(RequisitionRefused):
        to_stock_unit(Decimal("10000000"), "KG", "G")


# --- create -------------------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_sends_stores_the_pr_and_resyncs_after_commit(planner, sent_to, resyncs):
    mixed_order()

    requisition = create(planner, "1000001", "RM-SHORT", "30", TODAY)

    requisition.refresh_from_db()
    assert requisition.status == Requisition.Status.SENT
    assert requisition.pr_number == "10000000"
    assert requisition.sent_at is not None
    assert (requisition.quantity_entered, requisition.unit_entered) == (Decimal("30"), "PC")
    assert (requisition.quantity_sent, requisition.unit_sent) == (Decimal("30"), "PC")
    assert requisition.shortage_at_request == Decimal("30")
    assert requisition.items == "0001"
    assert requisition.created_by == planner
    [item] = sent_to.payloads[0]["to_PurchaseReqnItem"]
    assert item["RequestedQuantity"] == "30.000"
    assert requisition.payload == sent_to.payloads[0]
    # R-5: once, and not inside a transaction (the test's own outer block aside).
    assert resyncs == [("AUC1", resyncs[0][1])]


@pytest.mark.django_db(transaction=True)
def test_resync_runs_after_the_commit(planner, sent_to, resyncs):
    """R-5 in a real transaction setting: nothing is open when the re-sync starts."""
    mixed_order()

    create(planner, "1000001", "RM-SHORT", "30", TODAY)

    assert resyncs == [("AUC1", False)]


@pytest.mark.django_db
def test_a_failed_send_is_stored_and_not_resynced(planner, sent_to, resyncs):
    mixed_order()
    sent_to.answer = RequisitionResult(None, "Material\x00 is blocked.", {"body": "x\x00y"})

    requisition = create(planner, "1000001", "RM-SHORT", "30", TODAY)

    requisition.refresh_from_db()
    assert requisition.status == Requisition.Status.FAILED
    assert requisition.pr_number == ""
    assert requisition.error_message == "Material is blocked."
    assert requisition.response == {"body": "xy"}
    assert resyncs == []


@pytest.mark.django_db
def test_a_resync_error_is_logged_and_the_pr_stays_sent(planner, sent_to, monkeypatch, caplog):
    mixed_order()

    def broken_sync(plant: str) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(requisitions, "sync_plant", broken_sync)

    requisition = create(planner, "1000001", "RM-SHORT", "30", TODAY)

    assert requisition.status == Requisition.Status.SENT
    assert f"after {requisition.reference} failed" in caplog.text


@pytest.mark.django_db
def test_the_quantity_sent_is_in_the_stock_unit(planner, sent_to, resyncs):
    add_order("1000001", START, [("0001", "RM-1", "2", "KG")])
    add_stock("RM-1", "1500", unit="G")

    requisition = create(planner, "1000001", "RM-1", "0.5", TODAY)

    assert (requisition.quantity_sent, requisition.unit_sent) == (Decimal("500"), "G")


@pytest.mark.django_db
def test_a_second_open_request_is_a_duplicate(planner, sent_to, resyncs):
    """INV-7: one sent requisition blocks the next; nothing new is stored or sent."""
    mixed_order()
    first = create(planner, "1000001", "RM-SHORT", "30", TODAY)

    with pytest.raises(RequisitionRefused) as refused:
        create(planner, "1000001", "RM-SHORT", "30", TODAY)

    assert refused.value.reason == "duplicate"
    assert refused.value.existing == first
    assert first.reference in refused.value.message
    assert Requisition.objects.count() == 1
    assert len(sent_to.payloads) == 1


@pytest.mark.django_db
def test_a_failed_request_does_not_block_a_retry(planner, sent_to, resyncs):
    mixed_order()
    sent_to.answer = RequisitionResult(None, NOT_ACCEPTED, {})
    create(planner, "1000001", "RM-SHORT", "30", TODAY)
    sent_to.answer = RequisitionResult("10000001", "", {})

    retry = create(planner, "1000001", "RM-SHORT", "30", TODAY)

    assert retry.status == Requisition.Status.SENT
    assert Requisition.objects.count() == 2


@pytest.mark.django_db
def test_another_integrity_error_is_not_reported_as_a_duplicate(planner, sent_to, monkeypatch):
    mixed_order()

    def broken_create(**fields):
        raise IntegrityError("some other constraint")

    monkeypatch.setattr(Requisition.objects, "create", broken_create)

    with pytest.raises(IntegrityError):
        create(planner, "1000001", "RM-SHORT", "30", TODAY)


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["Viewer", "Admin", None])
def test_only_planner_and_manager_may_create(make_user, sent_to, role):
    """INV-1: refused before anything is stored or sent."""
    mixed_order()
    user = make_user(role) if role else make_user()

    with pytest.raises(PermissionDenied):
        create(user, "1000001", "RM-SHORT", "30", TODAY)

    assert Requisition.objects.count() == 0
    assert sent_to.payloads == []


@pytest.mark.django_db
def test_manager_may_create(make_user, sent_to, resyncs):
    mixed_order()

    assert create(make_user("Manager"), "1000001", "RM-LOW", "6", TODAY).pr_number


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("material", "quantity", "reason"),
    [("RM-COVER", "30", "not_requestable"), ("RM-SHORT", "0", "invalid_quantity")],
)
def test_refusals_store_and_send_nothing(planner, sent_to, material, quantity, reason):
    mixed_order()

    with pytest.raises(RequisitionRefused) as refused:
        create(planner, "1000001", material, quantity, TODAY)

    assert refused.value.reason == reason
    assert Requisition.objects.count() == 0
    assert sent_to.payloads == []
