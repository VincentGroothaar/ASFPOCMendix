"""AC-33 (REQ-9, change request): a Manager can set the buffer (0–100, at most 2 decimals);
statuses and tooltips use it at once. 0, 12.5 and 100 are accepted; -1, 100.01, 10.555 and
non-numbers are rejected with a message.

Accepted values are checked by their effect on a status: requirement 100 is Covered at
available ≥ 100 × (1 + buffer/100), and Low cover just below.
"""

from decimal import Decimal

import pytest

from tests.acceptance import builders
from tests.acceptance.support import Stock, days, one_component_order, read_page

pytestmark = pytest.mark.xfail(strict=True, reason="Not built yet: #34")


def status_with_available(fakes, client, available: str) -> str:
    fakes.sap.orders[:] = [one_component_order("1000001", days(1), "RM-1", "100")]
    fakes.sap.stock[:] = [Stock("RM-1", Decimal(available))]
    client.post("/plants/AUC1/refresh/")
    row = read_page(client.get("/orders/1000001/")).row_with("RM-1")
    for status in (builders.LOW_COVER, builders.COVERED, builders.SHORT):
        if status in row:
            return status
    raise AssertionError(f"No status in {row!r}")


@pytest.mark.parametrize(
    ("buffer", "covered_at", "low_at"),
    [("0", "100", "99.999"), ("12.5", "112.5", "112.499"), ("100", "200", "199.999")],
)
def test_ac_33_accepted_buffer_changes_statuses_at_once(
    fakes, clock, client_as, buffer, covered_at, low_at
):
    manager = client_as("Manager")

    manager.post("/settings/", builders.buffer_form(buffer))

    assert status_with_available(fakes, manager, covered_at) == builders.COVERED
    expected_below = builders.SHORT if buffer == "0" else builders.LOW_COVER
    assert status_with_available(fakes, manager, low_at) == expected_below


@pytest.mark.parametrize("value", ["-1", "100.01", "10.555", "abc", ""])
def test_ac_33_invalid_buffer_is_rejected_and_the_old_value_stays(fakes, clock, client_as, value):
    manager = client_as("Manager")
    fresh = read_page(manager.get("/settings/"))

    response = manager.post("/settings/", builders.buffer_form(value))

    assert response.status_code in (200, 400, 422)
    # The spec fixes no wording for the message; the page must show words it did not have.
    assert set(read_page(response).text.split()) - set(fresh.text.split())
    # Buffer still 10: available 110 is Covered, 109.999 is Low cover.
    assert status_with_available(fakes, manager, "110") == builders.COVERED
    assert status_with_available(fakes, manager, "109.999") == builders.LOW_COVER


@pytest.mark.parametrize("role", ["Viewer", "Planner"])
def test_ac_33_only_a_manager_can_change_the_buffer(client_as, role):
    assert client_as(role).post("/settings/", builders.buffer_form("20")).status_code == 403
