"""AC-38 (REQ-10 / INV-7): while a request awaits approval, no second request for the same
order + material can be created."""

import pytest

from tests.acceptance import builders
from tests.acceptance.support import ABOVE_LIMIT_CREATE, above_limit_plant, sync

pytestmark = pytest.mark.xfail(strict=True, reason="Not built yet: #32")


def test_ac_38_second_request_while_awaiting_approval_is_refused(fakes, clock, client_as):
    above_limit_plant(fakes.sap)
    sync()
    planner = client_as("Planner")
    planner.post(ABOVE_LIMIT_CREATE, builders.requisition_form("60"))

    second = planner.post(ABOVE_LIMIT_CREATE, builders.requisition_form("60"))

    assert second.status_code in (200, 400, 403, 409, 422)
    assert [r.status for r in builders.requisitions()] == [builders.AWAITING_APPROVAL]
