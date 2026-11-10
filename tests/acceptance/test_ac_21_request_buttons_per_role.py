"""AC-21 (REQ-5): Planner and Manager see a Request button on short and low cover components
without a requisition; a component whose latest requisition failed or was rejected shows that
label, which offers Retry or Request again; Viewer sees no Request, Retry or Request again.

Also the browser flow of the requisition side panel (ui-spec 4.2): Review → PR sent, and
Review → PR failed → Retry, and a Rejected label → Request again.
"""

from decimal import Decimal

import pytest

from tests.acceptance import builders
from tests.acceptance.support import (
    MIXED_ORDER,
    Component,
    Stock,
    load_mixed_order,
    read_page,
    sync,
)

DETAIL = f"/orders/{MIXED_ORDER}/"
ERROR = "Property 'PurchasingGroup' is required (item 1)."


def load_with_failed_requisition(fakes, client_as):
    """The mixed order plus RM-FAIL (short, with a low price), whose requisition failed."""
    load_mixed_order(fakes.sap)
    fakes.sap.orders[0].components.append(Component("RM-FAIL", Decimal("100"), item="0004"))
    fakes.sap.stock.append(Stock("RM-FAIL", Decimal("10"), price=Decimal("1")))
    sync()
    fakes.mock.error = ERROR
    client_as("Planner", "failed-request").post(
        f"{DETAIL}requisitions/?material=RM-FAIL", builders.requisition_form("90")
    )
    fakes.mock.error = None


def low_prices(fakes) -> None:
    for stock in fakes.sap.stock:
        stock.price = Decimal("1")  # low value: sent without approval


def click_request(page, material: str) -> None:
    row = page.get_by_role("row").filter(has_text=material)
    row.get_by_role("button", name="Request").click()


@pytest.mark.xfail(strict=True, reason="Not built yet: #28")
@pytest.mark.parametrize("role", ["Planner", "Manager"])
def test_ac_21_planner_and_manager_see_request_on_short_and_low_cover(
    fakes, clock, client_as, role
):
    load_with_failed_requisition(fakes, client_as)

    page = read_page(client_as(role).get(DETAIL))

    assert "Request" in page.row_with("RM-SHORT")
    assert "Request" in page.row_with("RM-LOW")
    assert "Request" not in page.row_with("RM-COVER")
    assert "PR failed" in page.row_with("RM-FAIL")


@pytest.mark.xfail(strict=True, reason="Not built yet: #29")
def test_ac_21_failed_requisition_offers_retry_to_planner_only(fakes, clock, client_as):
    """The failed requisition's page has Retry for a Planner (ui-spec 4.5), not for a Viewer."""
    load_with_failed_requisition(fakes, client_as)
    [failed] = builders.requisitions()

    planner_page = read_page(client_as("Planner").get(f"/requisitions/{failed.id}/"))
    viewer_page = read_page(client_as("Viewer").get(f"/requisitions/{failed.id}/"))

    assert planner_page.has_button("Retry")
    assert not viewer_page.has_button("Retry")


@pytest.mark.xfail(strict=True, reason="Not built yet: #28")
def test_ac_21_viewer_sees_no_request_retry_or_request_again(fakes, clock, client_as):
    load_with_failed_requisition(fakes, client_as)

    page = read_page(client_as("Viewer").get(DETAIL))

    for label in ("Request", "Retry", "Request again"):
        assert not page.has_button(label), f"Viewer should not see {label}"
    assert "PR failed" in page.row_with("RM-FAIL")


@pytest.mark.xfail(strict=True, reason="Not built yet: #33")
def test_ac_21_browser_rejected_label_offers_request_again(fakes, running_clock, browser_as):
    from django.test import Client
    from playwright.sync_api import expect

    load_mixed_order(fakes.sap)
    sync()
    # No price in SAP, so the requisition waits for approval (AC-34) and can be rejected.
    planner = builders.make_user("Planner", "pat")
    as_planner = Client()
    as_planner.force_login(planner)
    as_planner.post(f"{DETAIL}requisitions/?material=RM-SHORT", builders.requisition_form("30"))
    [waiting] = builders.requisitions()
    as_manager = Client()
    as_manager.force_login(builders.make_user("Manager", "boss"))
    as_manager.post(f"/requisitions/{waiting.id}/reject/", builders.reject_form(""))

    page = browser_as(DETAIL, user=planner)
    row = page.get_by_role("row").filter(has_text="RM-SHORT")
    row.get_by_role("button", name="Rejected").click()

    expect(page.get_by_role("button", name="Request again")).to_be_visible()


@pytest.mark.xfail(strict=True, reason="Not built yet: #28")
def test_ac_21_browser_side_panel_review_then_pr_sent(fakes, running_clock, browser_as):
    from playwright.sync_api import expect

    load_mixed_order(fakes.sap)
    low_prices(fakes)
    sync()

    page = browser_as(DETAIL, role="Planner")
    click_request(page, "RM-SHORT")

    expect(page.get_by_text("Review requisition")).to_be_visible()
    page.get_by_role("button", name="Send requisition").click()
    expect(page.get_by_text("PR sent").first).to_be_visible()
    expect(page.get_by_text("10000000").first).to_be_visible()


@pytest.mark.xfail(strict=True, reason="Not built yet: #28")
def test_ac_21_browser_side_panel_failed_then_retry(fakes, running_clock, browser_as):
    from playwright.sync_api import expect

    load_mixed_order(fakes.sap)
    low_prices(fakes)
    sync()
    fakes.mock.error = ERROR

    page = browser_as(DETAIL, role="Planner")
    click_request(page, "RM-SHORT")
    page.get_by_role("button", name="Send requisition").click()

    expect(page.get_by_text("PR failed").first).to_be_visible()
    page.get_by_role("button", name="Retry").click()
    expect(page.get_by_text("Review requisition")).to_be_visible()
