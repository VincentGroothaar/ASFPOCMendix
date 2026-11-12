"""Tests for the dashboard page, the sidebar parameters and Refresh (issue #30; AC-28f to AC-28i).

Like test_orders_view.py, the snapshot is written into the test database with a fresh
`synced_at`, so `ensure_fresh` never calls SAP.
"""

import html
import re
from datetime import timedelta
from urllib.parse import parse_qs, quote, urlsplit

import pytest
import time_machine
from pytest_django.asserts import assertContains, assertNotContains

from cockpit.models import Component, Requisition
from cockpit.services.dashboard import Dashboard, Slice
from cockpit.tests.test_order_list import make_order, make_requisition, make_stock
from cockpit.tests.test_orders_view import NOW, synced
from cockpit.views import _donut_segments

pytestmark = pytest.mark.django_db

TODAY = NOW.date()


@pytest.fixture(autouse=True)
def clock():
    with time_machine.travel(NOW, tick=False) as traveller:
        yield traveller


@pytest.fixture(autouse=True)
def no_sap(settings):
    settings.SAP_BASE_URL = ""
    settings.COCKPIT_PLANTS = ["AUC1", "USC1"]


# --- AC-28f: roles ------------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["Viewer", "Planner", "Manager"])
def test_business_roles_can_open_the_dashboard(client_as, role) -> None:
    synced()

    response = client_as(role).get("/dashboard/")

    assert response.status_code == 200
    assertContains(response, "Shortage dashboard")


@pytest.mark.parametrize("groups", [("Admin",), (), ("Viewer", "Planner")])
def test_admin_and_users_without_a_role_get_403(client_as, groups) -> None:
    assert client_as(*groups).get("/dashboard/").status_code == 403


def test_anonymous_users_go_to_login(client) -> None:
    response = client.get("/dashboard/")

    assert response.status_code == 302
    assert response["Location"].startswith("/accounts/login/")


# --- The page -----------------------------------------------------------------------------------


def test_the_page_shows_the_numbers_cards_and_tables(client_as) -> None:
    synced()
    make_stock("RM-1", "100")
    order = make_order("1000123", TODAY + timedelta(days=1), needs="150")
    Component.objects.filter(order=order).update(description="Steel bracket")
    make_requisition(order, "RM-1", Requisition.Status.AWAITING_APPROVAL)

    response = client_as("Viewer").get("/dashboard/")

    assertContains(response, "Plant AUC1 · start 03 Nov 2026 – 17 Nov 2026")
    assertContains(response, "Data as of 03 Nov 10:00")
    assertContains(response, "Orders by status")
    assertContains(
        response, 'aria-label="1 orders: 1 short, 0 low cover, 0 covered, 0 unit mismatch"'
    )
    assertContains(response, "Red orders")
    assertContains(response, "Short components · 1 material</span>", html=False)
    assertContains(response, "Low cover components")
    assertContains(response, "Open requisitions · 1 awaiting approval")
    assertContains(response, "Unit mismatch lines are excluded from component counts.")
    assertContains(response, "Steel bracket")
    assertContains(response, "50 PC")
    assertContains(response, 'href="/orders/1000123/"', count=2)  # affected order + order row
    assertContains(response, "04 Nov")


def test_overdue_is_marked_in_both_tables(client_as) -> None:
    synced()
    make_order("1000118", TODAY - timedelta(days=3), needs="5")

    response = client_as("Viewer").get("/dashboard/")

    assert response.content.decode().count(">Overdue<") == 2


def test_an_empty_range_shows_zeros_and_an_empty_line_in_both_tables(client_as) -> None:
    synced()

    response = client_as("Viewer").get("/dashboard/")

    assertContains(response, "No orders in this range.", count=2)
    assertContains(response, "<b>0</b>", count=1 + 4 + 4)  # donut total, 4 legend, 4 cards


def test_the_range_comes_from_the_url(client_as) -> None:
    synced("USC1")

    response = client_as("Viewer").get("/dashboard/?plant=USC1&from=2026-10-01&to=2026-10-31")

    assertContains(response, "Plant USC1 · start 01 Oct 2026 – 31 Oct 2026")


# --- AC-56 to AC-60: how much of each table is listed (#80) -------------------------------------


def make_red_orders(count: int) -> None:
    """`count` Short orders for RM-1 (no stock), numbered 1000101, 1000102, ..."""
    for index in range(1, count + 1):
        make_order(f"{1000100 + index}", TODAY + timedelta(days=1), needs="5")


def make_low_cover_orders(count: int) -> None:
    for index in range(1, count + 1):
        make_stock(f"LOW-{index}", "100")
        make_order(
            f"{2000100 + index}", TODAY + timedelta(days=2), needs="95", material=f"LOW-{index}"
        )


def test_a_material_lists_5_orders_then_and_n_more_as_plain_text(client_as) -> None:  # AC-56
    synced()
    make_red_orders(8)

    response = client_as("Viewer").get("/dashboard/")

    assertContains(response, 'class="dash-more">and 3 more</span>', count=1)
    # Orders 1 to 5 are linked in both tables, orders 6 to 8 only in the order table.
    assertContains(response, 'href="/orders/1000105/"', count=2)
    assertContains(response, 'href="/orders/1000106/"', count=1)
    assert 'href="/orders/?' not in response.content.decode().split("Shortage per order")[0]


def test_a_material_with_5_orders_has_no_and_n_more(client_as) -> None:  # AC-57
    synced()
    make_red_orders(5)

    response = client_as("Viewer").get("/dashboard/")

    assertNotContains(response, "dash-more")
    assertContains(response, 'href="/orders/1000105/"', count=2)


def test_the_order_table_lists_10_rows_and_a_footer_with_a_link_to_short_orders(
    client_as,
) -> None:  # AC-58, AC-59
    synced()
    make_red_orders(11)
    make_low_cover_orders(1)

    # The dashboard URL carries a page and a requisition filter that the link must not copy.
    response = client_as("Viewer").get("/dashboard/?plant=AUC1&page=3&requisition=none")

    content = response.content.decode()
    assertContains(response, "Showing 10 of 12 orders")
    assert 'href="/orders/1000111/"' not in content.split("Shortage per order")[1]  # row 11 hidden
    (href,) = re.findall(r'<a href="([^"]+)">Show all 11 short orders</a>', content)
    link = urlsplit(html.unescape(href))
    query = parse_qs(link.query)
    assert link.path == "/orders/"
    assert query["status"] == ["short"]
    assert query["plant"] == ["AUC1"]
    assert "from" in query and "to" in query
    assert "page" not in query and "requisition" not in query
    opened = client_as("Viewer").get(html.unescape(href))
    assertContains(opened, "Short orders")


def test_ten_rows_have_no_footer(client_as) -> None:  # AC-60
    synced()
    make_red_orders(10)

    response = client_as("Viewer").get("/dashboard/")

    assertNotContains(response, "Showing")
    assertNotContains(response, "Show all")


def test_hidden_low_cover_orders_get_a_footer_without_a_link(client_as) -> None:  # AC-60
    synced()
    make_red_orders(3)
    make_low_cover_orders(9)

    response = client_as("Viewer").get("/dashboard/")

    assertContains(response, "Showing 10 of 12 orders")
    assertNotContains(response, "Show all")


# --- The donut ----------------------------------------------------------------------------------


def dashboard_with(*counts: int) -> Dashboard:
    slices = tuple(
        Slice(key, key, count)
        for key, count in zip(("short", "low", "covered", "mismatch"), counts, strict=True)
    )
    return Dashboard(slices, sum(counts), 0, 0, 0, 0, 0, 0, (), ())


def test_the_donut_has_no_segments_when_the_total_is_0() -> None:
    assert _donut_segments(dashboard_with(0, 0, 0, 0)) == []


def test_one_slice_at_100_percent_is_a_full_ring() -> None:
    (segment,) = _donut_segments(dashboard_with(0, 0, 4, 0))

    assert (segment["key"], segment["length"], segment["gap"]) == ("covered", "100.0000", "0.0000")


def test_segments_follow_each_other_around_the_ring() -> None:
    first, second = _donut_segments(dashboard_with(1, 3, 0, 0))

    assert (first["length"], first["offset"]) == ("25.0000", "-0.0000")
    assert (second["length"], second["offset"]) == ("75.0000", "-25.0000")


# --- AC-28g: sync states ------------------------------------------------------------------------


def test_state_c_keeps_the_data_with_a_banner(client_as) -> None:
    synced(at=NOW - timedelta(minutes=1), error="SAP answered with HTTP 500.")
    make_order("1000101", TODAY, needs="5")

    response = client_as("Viewer").get("/dashboard/")

    assertContains(response, "SAP could not be reached. Showing data as of 03 Nov 09:59.")
    assertContains(response, "1000101")
    assertContains(response, ">Try again</button>")


def test_state_d_offers_try_again_and_a_link_to_choose_another_plant(client_as) -> None:
    response = client_as("Viewer").get("/dashboard/")

    assertContains(response, "No data for plant AUC1 yet")
    assertContains(response, ">Try again</button>")
    assertContains(response, 'href="/orders/?plant=AUC1&amp;filters=open"')
    assertNotContains(response, "Orders by status")


def test_state_d_hides_choose_another_plant_with_one_plant(client_as, settings) -> None:
    settings.COCKPIT_PLANTS = ["AUC1"]

    assertNotContains(client_as("Viewer").get("/dashboard/"), "Choose another plant")


def test_the_loading_indicator_is_there_for_state_b(client_as) -> None:
    synced()

    response = client_as("Viewer").get("/dashboard/")

    assertContains(response, "Loading orders from SAP for AUC1…")
    assertContains(response, 'hx-indicator=".sync-indicator"')


# --- AC-28i: plant and range through the sidebar, and Refresh -----------------------------------


def test_the_sidebar_carries_plant_and_range_to_orders_and_dashboard(client_as) -> None:
    synced("USC1")

    response = client_as("Viewer").get("/dashboard/?plant=USC1&from=2026-10-01&to=2026-10-31")

    query = "plant=USC1&amp;from=2026-10-01&amp;to=2026-10-31"
    assertContains(response, f'href="/orders/?{query}"')
    assertContains(response, f'href="/dashboard/?{query}"')
    assertContains(response, 'href="/requisitions/"')  # not a shared-range page


def test_the_sidebar_has_plain_links_without_parameters(client_as) -> None:
    synced()

    response = client_as("Viewer").get("/dashboard/")

    assertContains(response, 'href="/orders/"')
    assertContains(response, 'href="/dashboard/"')


def test_refresh_returns_to_the_dashboard_without_htmx(client_as) -> None:
    response = client_as("Viewer").post("/plants/AUC1/refresh/?next=/dashboard/%3Fplant%3DAUC1")

    assert response.status_code == 302
    assert response["Location"] == "/dashboard/?plant=AUC1"


@pytest.mark.parametrize(
    "target",
    [
        "https://evil.example/dashboard/",
        "//evil.example/",
        "/admin/",
        "/requisitions/",
        "javascript:1",
        " /orders/",
        "\t/orders/",
        "/orders/?" + "a" * 3000,
    ],
)
def test_refresh_ignores_any_other_next_target(client_as, target) -> None:
    response = client_as("Viewer").post(f"/plants/AUC1/refresh/?next={quote(target)}")

    assert response["Location"] == "/orders/?plant=AUC1"


def test_the_dashboard_refresh_button_remembers_the_page(client_as) -> None:
    synced()

    response = client_as("Viewer").get("/dashboard/?plant=AUC1")

    assertContains(response, 'hx-post="/plants/AUC1/refresh/?next=%2Fdashboard%2F%3Fplant%3DAUC1"')
