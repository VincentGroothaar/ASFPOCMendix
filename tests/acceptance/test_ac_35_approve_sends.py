"""AC-35 (REQ-10): approving sends it and stores the outcome as in AC-24 / AC-25.
Acceptance test against the local mock, plus the failure path with the fake mock."""

import os
import re

import pytest
import requests

from tests.acceptance import builders
from tests.acceptance.support import (
    ABOVE_LIMIT_CREATE,
    MOCK_SERVICE,
    above_limit_plant,
    sync,
)


@pytest.mark.skip(
    reason="Passes without approval before #32 (every requisition is sent at create, #27); "
    "un-skip in #32/#33"
)
def test_ac_35_approval_sends_to_the_local_mock(fakes, clock, client_as, live_mock):
    above_limit_plant(fakes.sap)
    sync()
    client_as("Manager", "manager-a").post(ABOVE_LIMIT_CREATE, builders.requisition_form("60"))
    [waiting] = builders.requisitions()

    client_as("Manager", "manager-b").post(f"/requisitions/{waiting.id}/approve/")

    [approved] = builders.requisitions()
    assert approved.status == builders.SENT
    assert re.fullmatch(r"\d{8}", approved.pr_number)
    in_mock = requests.get(
        f"{live_mock}{MOCK_SERVICE}/A_PurchaseRequisitionHeader('{approved.pr_number}')",
        headers={"APIKey": os.environ["MOCK_API_KEY"], "Accept": "application/json"},
        timeout=10,
    )
    assert in_mock.status_code == 200


@pytest.mark.xfail(strict=True, reason="Not built yet: #33")
def test_ac_35_approval_with_an_endpoint_error_is_stored_as_failed(fakes, clock, client_as):
    above_limit_plant(fakes.sap)
    sync()
    client_as("Manager", "manager-a").post(ABOVE_LIMIT_CREATE, builders.requisition_form("60"))
    [waiting] = builders.requisitions()
    fakes.mock.error = "Property 'PurchasingGroup' is required (item 1)."

    client_as("Manager", "manager-b").post(f"/requisitions/{waiting.id}/approve/")

    assert builders.requisitions()[0].status == builders.FAILED
    assert len(fakes.mock.posts) == 1
