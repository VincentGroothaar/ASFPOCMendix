"""Tests for the dashboard numbers (cockpit/services/dashboard.py, issue #30, AC-28a to AC-28e).

The snapshot rows are written into the test database like in test_order_list.py; SAP is not
involved. `numbers_for` runs the same steps as the view: scope, statuses, requisitions.
"""

from datetime import date
from decimal import Decimal

import pytest

from cockpit.models import Component, Requisition
from cockpit.services.dashboard import Dashboard, build_dashboard
from cockpit.services.order_list import (
    latest_requisitions,
    material_descriptions,
    orders_in_scope,
    plant_result,
)
from cockpit.tests.test_order_list import (
    PLANTS,
    TODAY,
    day,
    default_filters,
    filters,
    make_order,
    make_requisition,
    make_stock,
)

pytestmark = pytest.mark.django_db


def numbers_for(**changes) -> Dashboard:
    """The dashboard for the default range (or the given filters), as the view builds it."""
    scope_filters = filters(**changes)
    in_scope = orders_in_scope(scope_filters, TODAY)
    return build_dashboard(
        in_scope,
        plant_result("AUC1", TODAY),
        latest_requisitions(in_scope),
        TODAY,
        material_descriptions(in_scope),
    )


def slice_counts(dashboard: Dashboard) -> dict[str, int]:
    return {slice_.key: slice_.count for slice_ in dashboard.slices}


# --- AC-28a: the donut --------------------------------------------------------------------------


def test_every_order_is_in_one_slice_and_the_total_is_their_sum() -> None:
    make_stock("RM-1", "100")
    make_order("A", day(1), needs="150")  # short
    make_order("B", day(2), needs="10")  # covered (stock is 100, A takes it all: B is short too)
    make_stock("RM-2", "1000")
    make_order("C", day(3), needs="10", material="RM-2")  # covered

    dashboard = numbers_for()

    assert slice_counts(dashboard) == {"short": 2, "low": 0, "covered": 1, "mismatch": 0}
    assert dashboard.total == 3 == sum(slice_.count for slice_ in dashboard.slices)


def test_an_order_that_is_short_and_has_a_mismatch_line_counts_once_as_short() -> None:
    make_stock("RM-1", "5")
    order = make_order("A", day(1), needs="10")
    Component.objects.create(
        order=order,
        item="0002",
        material="RM-9",
        required_quantity=Decimal("1"),
        withdrawn_quantity=Decimal("0"),
        unit="PC",
    )
    make_stock("RM-9", "10", unit="KG")  # PC against KG: unit mismatch

    dashboard = numbers_for()

    assert slice_counts(dashboard) == {"short": 1, "low": 0, "covered": 0, "mismatch": 0}
    assert dashboard.total == 1


def test_an_order_with_only_a_mismatch_line_is_under_unit_mismatch_and_not_red() -> None:
    make_stock("RM-1", "10", unit="KG")
    make_order("A", day(1), needs="1")  # PC against KG

    dashboard = numbers_for()

    assert slice_counts(dashboard) == {"short": 0, "low": 0, "covered": 0, "mismatch": 1}
    assert dashboard.red_orders == 0
    assert dashboard.total == 1


def test_an_order_with_nothing_left_to_check_is_left_out_of_the_donut() -> None:
    order = make_order("A", day(1), needs="10")
    Component.objects.filter(order=order).update(withdrawn_quantity=Decimal("10"))  # issued

    dashboard = numbers_for()

    assert dashboard.total == 0
    assert dashboard.orders == ()


# --- AC-28b: the cards --------------------------------------------------------------------------


def test_component_cards_count_short_and_low_cover_lines_only() -> None:
    make_stock("RM-1", "5")
    make_stock("RM-2", "105")
    make_stock("RM-3", "10", unit="KG")
    make_stock("RM-4", "1000")
    order = make_order("A", day(1), needs="10")  # RM-1: short
    for item, material, needs, unit in (
        ("0002", "RM-2", "100", "PC"),  # low cover (105 < 110)
        ("0003", "RM-3", "1", "PC"),  # unit mismatch
        ("0004", "RM-4", "10", "PC"),  # covered
    ):
        Component.objects.create(
            order=order,
            item=item,
            material=material,
            required_quantity=Decimal(needs),
            withdrawn_quantity=Decimal("0"),
            unit=unit,
        )
    make_order("B", day(2), needs="1", material="RM-5")  # short, another material (no stock)

    dashboard = numbers_for()

    assert dashboard.red_orders == 2
    assert dashboard.short_components == 2
    assert dashboard.short_materials == 2
    assert dashboard.low_cover_components == 1


def test_open_requisitions_count_the_latest_row_per_order_and_material() -> None:
    a = make_order("A", day(1))
    b = make_order("B", day(2), material="RM-2")
    c = make_order("C", day(3), material="RM-3")
    d = make_order("D", day(4), material="RM-4", active=False)
    make_requisition(a, "RM-1", Requisition.Status.FAILED)
    make_requisition(a, "RM-1", Requisition.Status.SENT)  # failed then sent: one open
    make_requisition(b, "RM-2", Requisition.Status.FAILED)
    make_requisition(b, "RM-2", Requisition.Status.REJECTED)  # failed then rejected: none
    make_requisition(c, "RM-3", Requisition.Status.AWAITING_APPROVAL)
    make_requisition(d, "RM-4", Requisition.Status.SENT)  # inactive order: not in scope

    dashboard = numbers_for()

    assert dashboard.open_requisitions == 2
    assert dashboard.awaiting_approval == 1


def test_an_unknown_order_in_scope_is_skipped() -> None:
    make_order("A", day(1))

    dashboard = build_dashboard(["A", "GONE"], plant_result("AUC1", TODAY), [], TODAY)

    assert dashboard.total == 1


# --- AC-28c: shortage per material --------------------------------------------------------------


def test_shortage_per_material_sums_in_the_stock_unit_with_distinct_orders() -> None:
    make_stock("RM-1", "1", unit="KG")
    make_order("B", day(1), needs="2", unit="KG")  # first: 2 KG against 1 KG, short 1 KG
    make_order("A", day(2), needs="1500", unit="G")  # next: 1.5 KG, nothing left, short 1.5 KG

    row = numbers_for().materials[0]

    assert (row.material, row.shortage, row.unit, row.orders) == ("RM-1", Decimal("2.5"), "KG", 2)
    assert row.order_numbers == ("B", "A")  # by start date
    assert row.first_needed == day(1)
    assert row.overdue is False


def test_a_material_without_a_stock_row_has_stock_zero() -> None:
    make_order("A", day(1), needs="7", material="RM-7")

    row = numbers_for().materials[0]

    assert (row.shortage, row.unit) == (Decimal("7"), "PC")


def test_materials_are_sorted_by_first_needed_and_overdue_is_marked() -> None:
    make_order("A", day(3), needs="1", material="RM-B")
    make_order("B", day(-2), needs="1", material="RM-A")  # overdue
    make_order("C", day(3), needs="1", material="RM-A")
    make_order("D", day(3), needs="1", material="RM-C")

    rows = numbers_for().materials

    assert [row.material for row in rows] == ["RM-A", "RM-B", "RM-C"]
    assert [row.overdue for row in rows] == [True, False, False]
    assert rows[0].orders == 2


def test_materials_in_different_units_are_separate_rows_without_a_total() -> None:
    make_stock("RM-1", "0", unit="KG")
    make_order("A", day(1), needs="1", material="RM-1", unit="KG")
    make_order("B", day(1), needs="1", material="RM-2")

    rows = numbers_for().materials

    assert {(row.material, row.unit) for row in rows} == {("RM-1", "KG"), ("RM-2", "PC")}


def test_a_material_shows_the_component_description() -> None:
    order = make_order("A", day(1), needs="1")
    Component.objects.filter(order=order).update(description="Steel bracket")

    assert numbers_for().materials[0].description == "Steel bracket"


# --- AC-28d: shortage per order and the scope ---------------------------------------------------


def test_shortage_per_order_lists_short_and_low_cover_orders_red_first() -> None:
    make_stock("RM-1", "100")
    make_stock("RM-2", "1000")
    make_order("LOW", day(1), needs="95")  # low cover
    make_order("RED", day(3), needs="50", material="RM-3")  # no stock: short
    make_order("OK", day(2), needs="1", material="RM-2")  # covered: not listed

    rows = numbers_for().orders

    assert [(row.number, row.pill_key) for row in rows] == [("RED", "short"), ("LOW", "low")]
    assert rows[0].short_lines == 1
    assert rows[1].low_lines == 1


def test_the_dashboard_scope_equals_the_order_list_scope() -> None:
    make_order("OVERDUE", day(-3))  # outside the range, but overdue
    make_order("IN", day(2))
    make_order("LATER", day(40))  # after the range

    scope_filters = filters()

    assert set(orders_in_scope(scope_filters, TODAY)) == {"OVERDUE", "IN"}


def test_a_start_after_the_end_leaves_only_overdue_orders() -> None:
    make_order("OVERDUE", day(-3))
    make_order("IN", day(2))

    scope = orders_in_scope(filters(start_from=day(10), start_to=day(5)), TODAY)

    assert scope == ["OVERDUE"]


def test_the_counts_match_the_order_list() -> None:
    from cockpit.services.order_list import build_order_list

    make_stock("RM-1", "100")
    make_order("A", day(-1), needs="150")
    make_order("B", day(2), needs="10")
    make_order("C", day(3), needs="1", material="RM-9")

    dashboard = numbers_for()
    listed = build_order_list(default_filters(PLANTS, TODAY), TODAY)

    assert dashboard.red_orders == listed.counts.short
    assert dashboard.slices[1].count == listed.counts.low_cover
    assert dashboard.slices[2].count == listed.counts.covered


# --- AC-28e: statuses never depend on the range (INV-6) -----------------------------------------


def test_narrowing_the_range_changes_the_counts_but_not_a_status() -> None:
    make_stock("RM-1", "100")
    make_order("A", day(1), needs="80")
    make_order("B", day(9), needs="80")  # short because A took the stock

    wide = numbers_for()
    narrow = numbers_for(start_to=day(5))

    assert [row.number for row in wide.orders] == ["B"]
    assert narrow.orders == ()
    assert narrow.total == 1 and wide.total == 2
    assert plant_result("AUC1", TODAY).orders["B"].status.value == "short"


def test_the_default_range_is_today_to_two_weeks() -> None:
    assert default_filters(PLANTS, TODAY).start_to == date(2026, 11, 17)
