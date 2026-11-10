"""AC-7 (REQ-1): when a sync fails, the previous snapshot stays, and a banner shows the last
successful sync time. Fake SAP that fails after one successful sync."""

from datetime import timedelta

import pytest

from tests.acceptance.support import NOW, PLANT, Order, days, read_page

pytestmark = pytest.mark.xfail(strict=True, reason="Not built yet: #24")

BANNER = "SAP could not be reached. Showing data as of 03 Nov 10:00."


def test_ac_7_failed_sync_on_load_keeps_the_snapshot_and_shows_a_banner(fakes, clock, client_as):
    fakes.sap.orders.append(Order("1000101", days(1)))
    client = client_as("Viewer")
    client.get("/orders/")

    fakes.sap.failing = True
    clock.move_to(NOW + timedelta(minutes=6))
    page = read_page(client.get("/orders/"))

    assert BANNER in page.text
    assert "1000101" in page.text


def test_ac_7_failed_refresh_keeps_the_snapshot_and_shows_a_banner(fakes, clock, client_as):
    fakes.sap.orders.append(Order("1000101", days(1)))
    client = client_as("Viewer")
    client.get("/orders/")

    fakes.sap.failing = True
    clock.move_to(NOW + timedelta(minutes=1))
    client.post(f"/plants/{PLANT}/refresh/")
    page = read_page(client.get("/orders/"))

    assert BANNER in page.text
    assert "1000101" in page.text
