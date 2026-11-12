"""AC-52 on the Orders page (#25): below 900px the page has no horizontal scroll; the wide
order table scrolls inside its card instead."""

from playwright.sync_api import expect

from tests.acceptance.support import Stock, days, one_component_order, sync


def test_ac_52_order_list_has_no_horizontal_page_scroll_on_a_phone(
    fakes, running_clock, browser_as
):
    fakes.sap.orders.append(one_component_order("1000101", days(1), "RM-A", "100"))
    fakes.sap.stock.append(Stock("RM-A", 50))
    sync()
    page = browser_as("/orders/", role="Viewer")
    page.set_viewport_size({"width": 390, "height": 900})
    page.reload()

    expect(page.get_by_text("1000101")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth") <= 390
