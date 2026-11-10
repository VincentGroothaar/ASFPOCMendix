"""AC-31 (REQ-7 / INV-1): a direct POST to create a requisition as Viewer or Admin returns 403
and stores nothing."""

import pytest

from tests.acceptance import builders
from tests.acceptance.support import MIXED_ORDER, load_mixed_order, sync

pytestmark = pytest.mark.xfail(strict=True, reason="Not built yet: #27")


@pytest.mark.parametrize("role", ["Viewer", "Admin"])
def test_ac_31_viewer_and_admin_cannot_create_a_requisition(fakes, clock, client_as, role):
    load_mixed_order(fakes.sap)
    sync()

    response = client_as(role).post(
        f"/orders/{MIXED_ORDER}/requisitions/?material=RM-SHORT", builders.requisition_form("30")
    )

    assert response.status_code == 403
    assert builders.requisitions() == []
    assert fakes.mock.posts == []
