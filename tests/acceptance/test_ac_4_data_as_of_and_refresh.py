"""AC-4 (REQ-1): "Data as of" shows the sync time; Refresh runs a full sync and updates it;
a snapshot older than 5 minutes syncs on page load. Fake SAP and a fixed clock (10:00)."""

from datetime import timedelta

from tests.acceptance.support import NOW, PLANT, Order, days, read_page

ORDERS = "A_ProductionOrder_2"


def test_ac_4_data_as_of_shows_the_sync_time(fakes, clock, client_as):
    fakes.sap.orders.append(Order("1000101", days(1)))

    page = read_page(client_as("Viewer").get("/orders/"))

    assert "Data as of 03 Nov 10:00" in page.text


def test_ac_4_refresh_runs_a_full_sync_and_updates_the_time(fakes, clock, client_as):
    fakes.sap.orders.append(Order("1000101", days(1)))
    client = client_as("Viewer")
    client.get("/orders/")
    calls_before = len(fakes.sap.calls_to(ORDERS))

    fakes.sap.orders.append(Order("1000102", days(2)))
    clock.move_to(NOW + timedelta(minutes=2))
    client.post(f"/plants/{PLANT}/refresh/")
    page = read_page(client.get("/orders/"))

    assert len(fakes.sap.calls_to(ORDERS)) > calls_before
    assert "Data as of 03 Nov 10:02" in page.text
    assert "1000102" in page.text


def test_ac_4_snapshot_syncs_on_load_only_when_older_than_5_minutes(fakes, clock, client_as):
    fakes.sap.orders.append(Order("1000101", days(1)))
    client = client_as("Viewer")
    client.get("/orders/")
    calls_after_first_load = len(fakes.sap.calls_to(ORDERS))

    clock.move_to(NOW + timedelta(minutes=4))
    client.get("/orders/")
    assert len(fakes.sap.calls_to(ORDERS)) == calls_after_first_load, "4 minutes: no sync"

    clock.move_to(NOW + timedelta(minutes=6))
    page = read_page(client.get("/orders/"))
    assert len(fakes.sap.calls_to(ORDERS)) > calls_after_first_load, "6 minutes: sync"
    assert "Data as of 03 Nov 10:06" in page.text


def test_ac_4_browser_refresh_button_updates_data_as_of(fakes, running_clock, browser_as):
    from playwright.sync_api import expect

    fakes.sap.orders.append(Order("1000101", days(1)))
    page = browser_as("/orders/", role="Viewer")
    expect(page.get_by_text("1000102")).to_have_count(0)

    fakes.sap.orders.append(Order("1000102", days(2)))
    page.get_by_role("button", name="Refresh").click()

    expect(page.get_by_text("1000102")).to_be_visible()
    expect(page.get_by_text("Data as of")).to_be_visible()
