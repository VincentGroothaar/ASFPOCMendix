"""INV-1: a Viewer (or Admin) can never create a requisition, also not by a direct POST.
Posts to the create endpoint (also used by Retry and Request again) and expects 403."""

import pytest

from tests.acceptance import builders
from tests.acceptance.support import MIXED_ORDER, load_mixed_order, sync

pytestmark = pytest.mark.xfail(strict=True, reason="Not built yet: #22")


@pytest.mark.parametrize("role", ["Viewer", "Admin"])
@pytest.mark.parametrize("material", ["RM-SHORT", "RM-LOW", "RM-COVER"])
def test_inv_1_direct_post_as_viewer_or_admin_is_forbidden(fakes, clock, client_as, role, material):
    load_mixed_order(fakes.sap)
    sync()

    response = client_as(role).post(
        f"/orders/{MIXED_ORDER}/requisitions/?material={material}",
        builders.requisition_form("1"),
    )

    assert response.status_code == 403
    assert builders.requisitions() == []
    assert fakes.mock.posts == []
