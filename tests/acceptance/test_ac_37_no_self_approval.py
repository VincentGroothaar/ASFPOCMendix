"""AC-37 (REQ-10 / INV-8): Manager A cannot approve their own requisition (403); Manager B can.
Also the approval slide-in for an own request: both buttons disabled (ui-spec 4.4)."""

import pytest

from tests.acceptance import builders
from tests.acceptance.support import ABOVE_LIMIT_CREATE, above_limit_plant, sync

pytestmark = pytest.mark.xfail(strict=True, reason="Not built yet: #33")


def test_ac_37_manager_cannot_approve_own_but_another_manager_can(fakes, clock, client_as):
    above_limit_plant(fakes.sap)
    sync()
    manager_a = client_as("Manager", "manager-a")
    manager_a.post(ABOVE_LIMIT_CREATE, builders.requisition_form("60"))
    [waiting] = builders.requisitions()

    own = manager_a.post(f"/requisitions/{waiting.id}/approve/")

    assert own.status_code == 403
    assert builders.requisitions()[0].status == builders.AWAITING_APPROVAL
    assert fakes.mock.posts == []

    client_as("Manager", "manager-b").post(f"/requisitions/{waiting.id}/approve/")

    assert builders.requisitions()[0].status == builders.SENT


def test_ac_37_browser_own_request_has_disabled_decision_buttons(fakes, running_clock, browser_as):
    from django.test import Client
    from playwright.sync_api import expect

    above_limit_plant(fakes.sap)
    sync()
    manager = builders.make_user("Manager", "manager-a")
    client = Client()
    client.force_login(manager)
    client.post(ABOVE_LIMIT_CREATE, builders.requisition_form("60"))

    page = browser_as("/requisitions/", user=manager)
    page.get_by_role("button", name="Review").first.click()

    expect(page.get_by_text("Your own request: another manager decides.")).to_be_visible()
    expect(page.get_by_role("button", name="Approve and send")).to_be_disabled()
    expect(page.get_by_role("button", name="Reject")).to_be_disabled()
