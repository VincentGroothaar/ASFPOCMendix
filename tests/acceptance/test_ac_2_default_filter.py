"""AC-2 (REQ-1): without parameters, the range is today to today + 14 days and the plant is the
first in COCKPIT_PLANTS. Checked with a fixed clock (today = 3 Nov 2026)."""

import pytest

from tests.acceptance import builders
from tests.acceptance.support import Order, days, read_page

pytestmark = pytest.mark.xfail(strict=True, reason="Not built yet: #25")


def test_ac_2_default_range_is_today_to_today_plus_14(fakes, clock, client_as):
    fakes.sap.orders += [
        Order("1000101", days(0)),  # today: first day of the range
        Order("1000102", days(14)),  # last day of the range
        Order("1000103", days(15)),  # one day after the range
    ]

    page = read_page(client_as("Viewer").get("/orders/"))

    assert "1000101" in page.text
    assert "1000102" in page.text
    assert "1000103" not in page.text
    # The filter chip shows the range (ui-spec 3.6): `Start 03 Nov – 17 Nov 2026`.
    assert "03 Nov" in page.text and "17 Nov 2026" in page.text


def test_ac_2_default_plant_is_first_in_cockpit_plants(fakes, clock, client_as):
    fakes.sap.orders += [
        Order("1000201", days(1), plant="USC1"),
        Order("1000202", days(1), plant="AUC1"),
    ]

    with builders.plants_setting(["USC1", "AUC1"]):
        page = read_page(client_as("Viewer").get("/orders/"))

    assert "1000201" in page.text
    assert "1000202" not in page.text
