"""Browser checks for the order list (issue #25, local criteria AC-25-1 and AC-25-7).

Not a per-AC file: these go beyond the spec.md ACs and prove the HTMX wiring the design review
asked for (the name avoids spec.md AC-25, which is "requisition failed").
- R-B2 / R2-B1: the tile and Requisition filters survive each other and filter-bar changes.
- R2-I1: Reset to default keeps the list filters.
- R-B1 / R2-I2: after a plant change the header and Refresh belong to the new plant, also
  coming from state D.
- R3-I1: a filter change does not collapse the open filter bar.
- R3-I2: after Back the filter controls match the URL.
"""

from __future__ import annotations

import re
from decimal import Decimal

import pytest
from playwright.sync_api import expect

from tests.acceptance import builders
from tests.acceptance.support import (
    PLANT,
    Component,
    Order,
    Stock,
    days,
    one_component_order,
    sync,
)


def order_in(plant: str, number: str) -> Order:
    """A released order of `plant` starting tomorrow, with one component."""
    return Order(number, days(1), [Component("RM-A", Decimal("10"))], plant=plant)


def orders_with_requisitions(fakes) -> None:
    """1000101 Short with PR failed, 1000102 Short without, 1000103 Covered without."""
    fakes.sap.orders += [
        one_component_order("1000101", days(1), "RM-A", "100"),
        one_component_order("1000102", days(2), "RM-B", "100"),
        one_component_order("1000103", days(3), "RM-C", "10"),
    ]
    fakes.sap.stock += [Stock("RM-A", 50), Stock("RM-B", 50), Stock("RM-C", 100)]
    sync()
    planner = builders.make_user("Planner", "planner-filters")
    builders.store_requisition("1000101", "RM-A", "failed", planner)


def settled(page) -> None:
    """Wait until htmx has finished swapping and settling, so new elements are wired up.

    htmx binds the new Requisition select a moment after the swap (the settle step); a person
    is never that fast, but Playwright can be.
    """
    page.wait_for_function(
        "!document.querySelector('.htmx-request, .htmx-swapping, .htmx-settling, .htmx-added')"
    )


def short_tile(page):
    return page.get_by_role("button", name="Short", exact=False).first


def requisition_select(page):
    # By name: the label "Requisition" also matches the table heading "… · requisition: …".
    return page.locator('select[name="requisition"]')


def test_order_list_requisition_select_and_clear(fakes, running_clock, browser_as):
    orders_with_requisitions(fakes)
    page = browser_as("/orders/", role="Viewer")

    requisition_select(page).select_option(label="PR failed")
    expect(page.get_by_text("1000101")).to_be_visible()
    expect(page.get_by_text("1000102")).to_have_count(0)
    expect(page.get_by_role("heading", name="All orders · requisition: PR failed")).to_be_visible()
    expect(page).to_have_url(re.compile(r"requisition=failed"))
    settled(page)

    page.get_by_role("link", name="Clear").click()
    expect(page.get_by_text("1000102")).to_be_visible()
    expect(requisition_select(page)).to_have_value("")
    expect(page.get_by_role("link", name="Clear")).to_have_count(0)


def test_order_list_tile_and_requisition_filters_survive_each_other(
    fakes, running_clock, browser_as
):
    orders_with_requisitions(fakes)
    page = browser_as("/orders/", role="Viewer")

    short_tile(page).click()
    expect(short_tile(page)).to_have_attribute("aria-pressed", "true")
    settled(page)
    requisition_select(page).select_option(label="None")

    # Short and no requisition: only 1000102.
    expect(page.get_by_text("1000102")).to_be_visible()
    expect(page.get_by_text("1000101")).to_have_count(0)
    expect(page.get_by_text("1000103")).to_have_count(0)
    expect(short_tile(page)).to_have_attribute("aria-pressed", "true")
    settled(page)

    # A date change (filter bar) keeps both list filters (R2-B1).
    page.get_by_role("button", name="Edit filters").click()
    page.get_by_label("Start date to").fill(days(20).isoformat())
    expect(page).to_have_url(re.compile("to=" + days(20).isoformat()))
    expect(short_tile(page)).to_have_attribute("aria-pressed", "true")
    expect(requisition_select(page)).to_have_value("none")
    expect(page.get_by_text("1000101")).to_have_count(0)
    settled(page)

    # A tile click keeps the Requisition filter (R2-B1): Covered and none = 1000103.
    page.get_by_role("button", name="Covered", exact=False).first.click()
    expect(page.get_by_text("1000103")).to_be_visible()
    expect(page.get_by_text("1000102")).to_have_count(0)
    expect(requisition_select(page)).to_have_value("none")


def test_order_list_reset_keeps_the_list_filters(fakes, running_clock, browser_as):
    orders_with_requisitions(fakes)
    page = browser_as(f"/orders/?from={days(1).isoformat()}&to={days(2).isoformat()}", "Viewer")

    short_tile(page).click()
    expect(short_tile(page)).to_have_attribute("aria-pressed", "true")
    settled(page)
    page.get_by_role("button", name="Edit filters").click()
    page.get_by_role("link", name="Reset to default").click()

    expect(page.get_by_text("Start 03 Nov – 17 Nov 2026")).to_be_visible()
    expect(short_tile(page)).to_have_attribute("aria-pressed", "true")
    expect(page.get_by_label("Start date from")).to_have_value(days(0).isoformat())


def test_order_list_open_filter_bar_stays_open_after_a_change(fakes, running_clock, browser_as):
    orders_with_requisitions(fakes)
    page = browser_as("/orders/", role="Viewer")

    page.get_by_role("button", name="Edit filters").click()
    page.get_by_label("Start date from").fill(days(2).isoformat())

    expect(page.get_by_text(f"Start {days(2).strftime('%d %b')} – 17 Nov 2026")).to_be_visible()
    expect(page.get_by_role("button", name="Hide filters")).to_have_attribute(
        "aria-expanded", "true"
    )
    expect(page.get_by_label("Start date to")).to_be_visible()


@pytest.fixture
def two_plants():
    with builders.plants_setting([PLANT, "USC1"]):
        yield


def test_order_list_refresh_follows_a_plant_change(fakes, running_clock, browser_as, two_plants):
    fakes.sap.orders += [
        one_component_order("1000101", days(1), "RM-A", "10"),
        order_in("USC1", "2000101"),
    ]
    page = browser_as("/orders/", role="Viewer")
    expect(page.get_by_text("1000101")).to_be_visible()

    page.get_by_role("button", name="Edit filters").click()
    page.get_by_label("Plant").select_option("USC1")
    expect(page.get_by_text("2000101")).to_be_visible()
    expect(page.get_by_text("Plant USC1", exact=True)).to_be_visible()

    fakes.sap.orders.append(order_in("USC1", "2000102"))
    page.get_by_role("button", name="Refresh").click()

    expect(page.get_by_text("2000102")).to_be_visible()
    expect(page.get_by_label("Plant")).to_have_value("USC1")


def test_order_list_back_shows_controls_that_match_the_url(
    fakes, running_clock, browser_as, two_plants
):
    fakes.sap.orders += [
        one_component_order("1000101", days(1), "RM-A", "10"),
        order_in("USC1", "2000101"),
    ]
    page = browser_as("/orders/", role="Viewer")
    page.get_by_role("button", name="Edit filters").click()
    page.get_by_label("Plant").select_option("USC1")
    expect(page.get_by_text("2000101")).to_be_visible()

    page.go_back()

    expect(page.get_by_text("1000101")).to_be_visible()
    expect(page.get_by_text("Plant AUC1", exact=True)).to_be_visible()
    expect(page.get_by_label("Plant")).to_have_value("AUC1")


def test_order_list_from_state_d_a_plant_change_restores_the_header(
    fakes, running_clock, browser_as, two_plants
):
    fakes.sap.orders.append(order_in("USC1", "2000101"))
    fakes.sap.failing = True
    page = browser_as("/orders/", role="Viewer")
    expect(page.get_by_text(f"No data for plant {PLANT} yet")).to_be_visible()
    expect(page.get_by_role("button", name="Refresh")).to_have_count(0)

    fakes.sap.failing = False
    page.get_by_role("button", name="Choose another plant").click()
    expect(page.get_by_label("Plant")).to_be_focused()
    page.get_by_label("Plant").select_option("USC1")

    expect(page.get_by_text("2000101")).to_be_visible()
    expect(page.get_by_text("Data as of")).to_be_visible()
    expect(page.get_by_role("button", name="Refresh")).to_be_visible()


def test_order_list_tile_tooltips_show_on_hover_and_focus_with_the_buffer(
    fakes, running_clock, browser_as
):
    """AC-20 (tiles) on the Orders page: the ⓘ shows the 5.2 text with the current buffer."""
    orders_with_requisitions(fakes)
    page = browser_as("/orders/", role="Viewer")
    info = page.get_by_role("button", name="What does Covered mean?")
    tooltip = page.get_by_text("All components have at least 10% to spare.")  # default buffer

    expect(tooltip).to_be_hidden()
    info.hover()
    expect(tooltip).to_be_visible()
    page.mouse.move(0, 0)
    expect(tooltip).to_be_hidden()
    info.focus()
    expect(tooltip).to_be_visible()
