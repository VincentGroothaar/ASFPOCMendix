"""AC-1 (REQ-1): the list shows only active released orders of the selected plant with a start
date inside the range (inclusive), plus overdue ones.

Constructed data (spec.md, "Proven by unit tests only"): the sandbox has no order in range.
The fake SAP applies the app's $filter like the sandbox does, so an order the app fails to
filter out in its SAP query shows up here.
"""

from tests.acceptance.support import PLANT, Order, days, read_page

SHOWN = {
    "1000101": "released, starts inside the range",
    "1000102": "released, starts on the first day of the range",
    "1000103": "released, starts on the last day of the range",
    "1000104": "released, overdue (started before today)",
}
HIDDEN = {
    "1000201": "released, starts after the range",
    "1000202": "not released",
    "1000203": "released but delivered",
    "1000204": "released, inside the range, but in another plant",
    "1000205": "released, starts after today but before the range",
}


def load_orders(sap) -> None:
    sap.orders += [
        Order("1000101", days(5)),
        Order("1000102", days(2)),
        Order("1000103", days(9)),
        Order("1000104", days(-4)),
        Order("1000201", days(10)),
        Order("1000202", days(5), released=False),
        Order("1000203", days(5), delivered=True),
        Order("1000204", days(5), plant="USC1"),
        Order("1000205", days(1)),
    ]


def test_ac_1_list_shows_released_orders_in_range_plus_overdue(fakes, clock, client_as):
    load_orders(fakes.sap)

    response = client_as("Viewer").get(
        "/orders/", {"plant": PLANT, "from": days(2).isoformat(), "to": days(9).isoformat()}
    )

    assert response.status_code == 200
    page = read_page(response)
    for number, why in SHOWN.items():
        assert number in page.text, f"Order {number} ({why}) should be listed"
    for number, why in HIDDEN.items():
        assert number not in page.text, f"Order {number} ({why}) should not be listed"


def test_ac_1_browser_status_tile_filters_the_list(fakes, running_clock, browser_as):
    """ui-spec 3.4: a status tile is a toggle that filters the list; clicking it again clears."""
    from playwright.sync_api import expect

    from tests.acceptance.support import Component, Stock

    fakes.sap.orders += [
        Order("1000301", days(1), [Component("RM-A", 100)]),
        Order("1000302", days(2), [Component("RM-B", 100)]),
    ]
    fakes.sap.stock += [Stock("RM-A", 50), Stock("RM-B", 500)]

    page = browser_as("/orders/", role="Viewer")
    short_tile = page.get_by_role("button", name="Short", exact=False).first
    short_tile.click()

    expect(page.get_by_text("1000301")).to_be_visible()
    expect(page.get_by_text("1000302")).to_have_count(0)
    expect(short_tile).to_have_attribute("aria-pressed", "true")

    short_tile.click()
    expect(page.get_by_text("1000302")).to_be_visible()
