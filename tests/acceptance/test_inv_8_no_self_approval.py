"""INV-8: a Manager can never approve a requisition they created. Manager A creating and
approving gets 403; Manager B approving succeeds. Rejecting your own is refused too."""

import pytest

from tests.acceptance import builders
from tests.acceptance.support import ABOVE_LIMIT_CREATE, above_limit_plant, sync

pytestmark = pytest.mark.xfail(strict=True, reason="Not built yet: #33")


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_inv_8_own_requisition_cannot_be_decided(fakes, clock, client_as, decision):
    above_limit_plant(fakes.sap)
    sync()
    manager_a = client_as("Manager", "manager-a")
    manager_a.post(ABOVE_LIMIT_CREATE, builders.requisition_form("60"))
    [waiting] = builders.requisitions()

    response = manager_a.post(f"/requisitions/{waiting.id}/{decision}/", builders.reject_form())

    assert response.status_code == 403
    assert builders.requisitions()[0].status == builders.AWAITING_APPROVAL


def test_inv_8_another_manager_can_approve(fakes, clock, client_as):
    above_limit_plant(fakes.sap)
    sync()
    client_as("Manager", "manager-a").post(ABOVE_LIMIT_CREATE, builders.requisition_form("60"))
    [waiting] = builders.requisitions()

    response = client_as("Manager", "manager-b").post(f"/requisitions/{waiting.id}/approve/")

    assert response.status_code in (200, 302)
    assert builders.requisitions()[0].status == builders.SENT
