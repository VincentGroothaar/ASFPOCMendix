"""AC-65 (REQ-5, #83): a requisition sent with MOCK_PR_BASE_URL set to the full service root of
the local mock (ending in /sap/opu/odata/sap/API_PURCHASEREQ_PROCESS_SRV) gets a PR number, as
in AC-24, not a 404. Acceptance test against the local mock."""

import re
from decimal import Decimal

from django.test import override_settings

from tests.acceptance import builders
from tests.acceptance.support import MIXED_ORDER, MOCK_SERVICE, load_mixed_order, sync


def test_ac_65_service_root_as_base_url_reaches_the_local_mock(fakes, clock, client_as, live_mock):
    load_mixed_order(fakes.sap)
    for stock in fakes.sap.stock:
        stock.price = Decimal("1")  # below the approval limit
    planner = client_as("Planner")
    sync()

    with override_settings(MOCK_PR_BASE_URL=f"{live_mock.rstrip('/')}{MOCK_SERVICE}"):
        planner.post(
            f"/orders/{MIXED_ORDER}/requisitions/?material=RM-SHORT",
            builders.requisition_form("30"),
        )

    [requisition] = builders.requisitions()
    assert requisition.status == builders.SENT
    assert re.fullmatch(r"\d{8}", requisition.pr_number)
