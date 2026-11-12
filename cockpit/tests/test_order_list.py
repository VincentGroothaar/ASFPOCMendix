"""Tests for the order list service (cockpit/services/order_list.py, issue #25).

The snapshot rows are written straight into the test database; SAP is not involved.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import User

from cockpit.models import Component, ProductionOrder, Requisition, Stock
from cockpit.services.order_list import (
    OrderFilters,
    RequisitionFilter,
    build_order_list,
    default_filters,
    format_percent,
    order_requisition_labels,
    parse_filters,
    tile_tooltips,
)
from cockpit.services.shortage import Status

PLANTS = ["AUC1", "USC1"]
TODAY = date(2026, 11, 3)
SYNCED = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)


def day(n: int) -> date:
    return TODAY + timedelta(days=n)


def make_order(
    number: str,
    start: date,
    needs: str = "10",
    material: str = "RM-1",
    plant: str = "AUC1",
    active: bool = True,
    unit: str = "PC",
) -> ProductionOrder:
    """An order with one component that needs `needs` of `material`."""
    order = ProductionOrder.objects.create(
        number=number,
        plant=plant,
        material="FG-1",
        description="Bike",
        quantity=Decimal("1"),
        unit="PC",
        start_date=start,
        is_active=active,
        synced_at=SYNCED,
    )
    Component.objects.create(
        order=order,
        item="0001",
        material=material,
        required_quantity=Decimal(needs),
        withdrawn_quantity=Decimal("0"),
        unit=unit,
    )
    return order


def make_stock(material: str, quantity: str, plant: str = "AUC1", unit: str = "PC") -> None:
    Stock.objects.create(
        plant=plant, material=material, quantity=Decimal(quantity), unit=unit, synced_at=SYNCED
    )


def make_requisition(order: ProductionOrder, material: str, status: str) -> Requisition:
    user, _ = User.objects.get_or_create(username="planner")
    return Requisition.objects.create(
        order=order,
        material=material,
        items="0001",
        quantity_entered=Decimal("1"),
        unit_entered="PC",
        quantity_sent=Decimal("1"),
        unit_sent="PC",
        delivery_date=order.start_date,
        status=status,
        created_by=user,
    )


def filters(**changes) -> OrderFilters:
    base = default_filters(PLANTS, TODAY)
    return OrderFilters(**{**base.__dict__, **changes})


def numbers(order_list) -> list[str]:
    return [row.number for row in order_list.rows]


# --- parse_filters: every bad value falls back to its default (decision 6) ----------------------


def test_defaults_are_the_first_plant_and_today_to_today_plus_14() -> None:
    assert parse_filters({}, PLANTS, TODAY) == OrderFilters(
        plant="AUC1",
        start_from=TODAY,
        start_to=day(14),
        status=None,
        requisition=None,
        page=1,
    )


def test_valid_values_are_read() -> None:
    params = {
        "plant": "USC1",
        "from": "2026-11-01",
        "to": "2026-11-30",
        "status": "low_cover",
        "requisition": "awaiting_approval",
        "page": "2",
    }

    assert parse_filters(params, PLANTS, TODAY) == OrderFilters(
        plant="USC1",
        start_from=date(2026, 11, 1),
        start_to=date(2026, 11, 30),
        status=Status.LOW_COVER,
        requisition=RequisitionFilter.AWAITING_APPROVAL,
        page=2,
    )


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("plant", "1710"),  # not in COCKPIT_PLANTS: never synced
        ("plant", "auc1"),
        ("plant", " AUC1"),
        ("from", "03-11-2026"),
        ("from", "2026-02-30"),
        ("to", "tomorrow"),
        ("status", "unit_mismatch"),  # not a tile
        ("status", "SHORT"),
        ("requisition", "rejected"),  # not offered on the order list
        ("page", "0"),
        ("page", "-1"),
        ("page", "two"),
        ("page", "99999999999999999999999"),
    ],
)
def test_a_bad_value_falls_back_to_its_default(name, value) -> None:
    parsed = parse_filters({name: value}, PLANTS, TODAY)

    if name == "page" and value.isdigit() and int(value) >= 1:
        assert parsed.page == int(value)  # a huge page is valid; get_page shows the last page
    else:
        assert parsed == default_filters(PLANTS, TODAY)


def test_from_after_to_is_kept() -> None:
    parsed = parse_filters({"from": "2026-11-20", "to": "2026-11-10"}, PLANTS, TODAY)

    assert (parsed.start_from, parsed.start_to) == (date(2026, 11, 20), date(2026, 11, 10))


def test_query_leaves_out_empty_list_filters_and_page_1() -> None:
    assert filters().query() == {"plant": "AUC1", "from": "2026-11-03", "to": "2026-11-17"}
    assert filters().query(status=Status.SHORT, page=3) == {
        "plant": "AUC1",
        "from": "2026-11-03",
        "to": "2026-11-17",
        "status": "short",
        "page": "3",
    }


# --- Scope: range plus overdue (AC-1, AC-3) -----------------------------------------------------


@pytest.mark.django_db
def test_scope_is_the_range_inclusive_plus_overdue_orders() -> None:
    make_order("1000101", day(2))  # first day of the range
    make_order("1000102", day(9))  # last day of the range
    make_order("1000103", day(-4))  # overdue
    make_order("1000201", day(10))  # after the range
    make_order("1000202", day(1))  # after today, before the range
    make_order("1000203", day(5), active=False)  # no longer released
    make_order("1000204", day(5), plant="USC1")  # another plant
    make_stock("RM-1", "1000")

    result = build_order_list(filters(start_from=day(2), start_to=day(9)), TODAY)

    assert numbers(result) == ["1000103", "1000101", "1000102"]
    assert [row.overdue for row in result.rows] == [True, False, False]


@pytest.mark.django_db
def test_from_after_to_shows_only_overdue_orders() -> None:
    make_order("1000101", day(-1))
    make_order("1000102", day(3))

    result = build_order_list(filters(start_from=day(9), start_to=day(2)), TODAY)

    assert numbers(result) == ["1000101"]


@pytest.mark.django_db
def test_sorted_by_start_date_then_number() -> None:
    make_order("1000103", day(1))
    make_order("1000101", day(2))
    make_order("1000102", day(1))

    assert numbers(build_order_list(filters(), TODAY)) == ["1000102", "1000103", "1000101"]


# --- Statuses come from the whole plant (INV-6) -------------------------------------------------


@pytest.mark.django_db
def test_an_order_outside_the_range_still_takes_its_stock_first() -> None:
    make_order("1000101", day(1), needs="60")  # outside the narrow range, earlier
    make_order("1000102", day(5), needs="60")
    make_stock("RM-1", "100")

    narrow = build_order_list(filters(start_from=day(5), start_to=day(5)), TODAY)

    assert numbers(narrow) == ["1000102"]
    assert narrow.rows[0].status == Status.SHORT
    assert narrow.rows[0].pill_key == "short"


@pytest.mark.django_db
def test_an_order_with_only_mismatched_lines_has_no_status_and_counts_only_in_all() -> None:
    make_order("1000101", day(1), unit="PC")
    make_stock("RM-1", "5", unit="KG")  # PC cannot be converted to KG: unit mismatch
    make_order("1000102", day(2), material="RM-2")
    make_stock("RM-2", "100")

    result = build_order_list(filters(), TODAY)

    mismatch = result.rows[0]
    assert (mismatch.status, mismatch.pill_key, mismatch.unit_mismatch) == (None, None, True)
    assert result.counts.all == 2
    assert (result.counts.short, result.counts.low_cover, result.counts.covered) == (0, 0, 1)
    for status in (Status.SHORT, Status.LOW_COVER, Status.COVERED):
        assert "1000101" not in numbers(build_order_list(filters(status=status), TODAY))


# --- Requisition labels (decision 5, R-I2) ------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("history", "label"),
    [
        (["failed", "sent"], "sent"),  # a retry that worked
        (["failed", "rejected"], None),  # the latest one counts, even when Rejected
        (["rejected", "awaiting_approval"], "awaiting_approval"),
        (["sent", "failed"], "failed"),  # cannot happen today (INV-7), but the latest wins
    ],
)
def test_the_latest_requisition_per_material_counts(history, label) -> None:
    order = make_order("1000101", day(1))
    for status in history:
        make_requisition(order, "RM-1", status)

    assert order_requisition_labels([order.id]).get(order.id) == label


@pytest.mark.django_db
def test_the_most_urgent_material_label_wins() -> None:
    order = make_order("1000101", day(1))
    make_requisition(order, "RM-1", "sent")
    make_requisition(order, "RM-2", "awaiting_approval")
    make_requisition(order, "RM-3", "failed")
    other = make_order("1000102", day(1))
    make_requisition(other, "RM-1", "sent")
    make_requisition(other, "RM-2", "awaiting_approval")

    labels = order_requisition_labels([order.id, other.id])

    assert labels == {order.id: "failed", other.id: "awaiting_approval"}


@pytest.mark.django_db
def test_latest_means_highest_id_even_with_equal_times() -> None:
    order = make_order("1000101", day(1))
    first = make_requisition(order, "RM-1", "failed")
    second = make_requisition(order, "RM-1", "sent")
    Requisition.objects.filter(id__in=[first.id, second.id]).update(created_at=SYNCED)

    assert order_requisition_labels([order.id]) == {order.id: "sent"}


# --- Requisition filter and counts (decision 3) -------------------------------------------------


@pytest.mark.django_db
def test_requisition_filter_and_tile_counts() -> None:
    short_with_pr = make_order("1000101", day(1), needs="100", material="RM-1")
    make_order("1000102", day(2), needs="100", material="RM-2")  # short, no requisition
    make_order("1000103", day(3), needs="10", material="RM-3")  # covered, no requisition
    make_stock("RM-1", "50")
    make_stock("RM-2", "50")
    make_stock("RM-3", "100")
    make_requisition(short_with_pr, "RM-1", "sent")

    none = build_order_list(filters(requisition=RequisitionFilter.NONE), TODAY)
    sent = build_order_list(filters(requisition=RequisitionFilter.SENT), TODAY)
    short_none = build_order_list(
        filters(requisition=RequisitionFilter.NONE, status=Status.SHORT), TODAY
    )

    assert numbers(none) == ["1000102", "1000103"]
    assert (none.counts.all, none.counts.short, none.counts.covered) == (2, 1, 1)
    assert numbers(sent) == ["1000101"]
    assert sent.rows[0].requisition == "sent"
    assert numbers(short_none) == ["1000102"]
    # The selected tile never narrows the counts.
    assert short_none.counts == none.counts


# --- Pagination (AC-6) --------------------------------------------------------------------------


@pytest.mark.django_db
def test_fifty_per_page_and_a_page_past_the_end_shows_the_last_page() -> None:
    for k in range(1, 61):
        make_order(f"{1000100 + k}", day(0), needs="1")
    make_stock("RM-1", "1000")

    first = build_order_list(filters(), TODAY)
    past_the_end = build_order_list(filters(page=9), TODAY)

    assert len(first.rows) == 50 and first.page.paginator.count == 60
    assert numbers(past_the_end) == [f"{1000100 + k}" for k in range(51, 61)]


# --- Tooltips -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "text"),
    [(Decimal("10"), "10%"), (Decimal("10.00"), "10%"), (Decimal("12.50"), "12.5%")],
)
def test_format_percent(value, text) -> None:
    assert format_percent(value) == text


def test_tile_tooltips_show_the_buffer() -> None:
    tips = tile_tooltips(Decimal("12.50"))

    assert tips[Status.LOW_COVER] == (
        "All components are covered, but at least one has less than 12.5% to spare."
    )
    assert tips[Status.COVERED] == "All components have at least 12.5% to spare."
    assert tips[Status.SHORT].startswith("At least one component has less stock available")
