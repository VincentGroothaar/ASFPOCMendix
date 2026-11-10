"""AC-3 (REQ-1): overdue orders show an "overdue" badge and are listed before the range.
Constructed snapshot, fixed clock (today = 3 Nov 2026)."""

import pytest

from tests.acceptance.support import Order, days, read_page

pytestmark = pytest.mark.xfail(strict=True, reason="Not built yet: #25")


def test_ac_3_overdue_orders_have_a_badge_and_come_first(fakes, clock, client_as):
    # Order numbers deliberately run against the date order.
    fakes.sap.orders += [
        Order("1000101", days(3)),
        Order("1000102", days(1)),
        Order("1000103", days(-2)),
    ]

    page = read_page(client_as("Viewer").get("/orders/"))

    assert "Overdue" in page.row_with("1000103")
    assert "Overdue" not in page.row_with("1000102")
    assert "Overdue" not in page.row_with("1000101")
    positions = [page.text.index(number) for number in ("1000103", "1000102", "1000101")]
    assert positions == sorted(positions), "Expected overdue first, then by start date"
