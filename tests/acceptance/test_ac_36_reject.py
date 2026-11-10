"""AC-36 (REQ-10): rejecting takes an optional reason, shows it to the planner when given, and
allows a new request for that order + material."""

import pytest

from tests.acceptance import builders
from tests.acceptance.support import ABOVE_LIMIT_CREATE, above_limit_plant, read_page, sync

pytestmark = pytest.mark.xfail(strict=True, reason="Not built yet: #33")


@pytest.mark.parametrize("reason", ["Too expensive, order from stock in USC1", ""])
def test_ac_36_reject_with_optional_reason_then_request_again(fakes, clock, client_as, reason):
    above_limit_plant(fakes.sap)
    sync()
    planner = client_as("Planner", "pat")
    planner.post(ABOVE_LIMIT_CREATE, builders.requisition_form("60"))
    [waiting] = builders.requisitions()

    client_as("Manager").post(f"/requisitions/{waiting.id}/reject/", builders.reject_form(reason))

    [rejected] = builders.requisitions()
    assert rejected.status == builders.REJECTED
    page = read_page(planner.get(f"/requisitions/{rejected.id}/"))
    assert "Rejected" in page.text
    if reason:
        assert f"Reason: {reason}" in page.text
    else:
        assert "Reason:" not in page.text

    planner.post(ABOVE_LIMIT_CREATE, builders.requisition_form("60"))

    assert [r.status for r in builders.requisitions()] == [
        builders.REJECTED,
        builders.AWAITING_APPROVAL,
    ]
