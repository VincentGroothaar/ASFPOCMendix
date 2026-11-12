"""Browser checks for the requisition side panel (#28: P-1, P-3, P-5, P-7).

The panel is HTMX, so these are the proof that the swaps work in a real browser: the rows
change after Send (the out-of-band `<template>` swap), the highlight moves and clears, 409 is
shown in the panel, and the quantity preview follows the field. The write client is a fake
(the live server runs in this process). Screenshots are saved under test-results/requisition-panel/.
"""

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from django.utils import timezone
from playwright.sync_api import Page, expect
from pytest_django.live_server_helper import LiveServer

from cockpit.models import Component, PlantSnapshot, ProductionOrder, Requisition, Stock
from cockpit.services import requisitions
from sap.requisitions import RequisitionResult
from tests.test_browser_ui import DESKTOP, log_in, make_user

SCREENSHOTS = Path(__file__).resolve().parent.parent / "test-results" / "requisition-panel"
ORDER = "/orders/1000123/"


def screenshot(page: Page, name: str) -> None:
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SCREENSHOTS / f"{name}.png"), full_page=True)


class FakeMock:
    """Stands in for the requisition mock: a PR number, or the `error` text when it is set."""

    def __init__(self) -> None:
        self.error = ""
        self.payloads: list[dict] = []

    def __call__(self, payload: dict) -> RequisitionResult:
        self.payloads.append(payload)
        if self.error:
            return RequisitionResult(None, self.error, {"status": 400})
        return RequisitionResult("10000042", "", {"status": 201})


@pytest.fixture
def mock(monkeypatch) -> FakeMock:
    fake = FakeMock()
    monkeypatch.setattr(requisitions, "create_requisition", fake)
    monkeypatch.setattr(requisitions, "sync_plant", lambda plant: None)
    return fake


@pytest.fixture
def order_page(transactional_db, settings) -> str:
    """One order: RM-100 short, RM-110 low cover, RM-120 short in KG with stock in G."""
    settings.SAP_BASE_URL = ""
    now = timezone.now()
    PlantSnapshot.objects.create(plant="AUC1", synced_at=now)
    order = ProductionOrder.objects.create(
        number="1000123",
        plant="AUC1",
        material="FG-210",
        description="Pump assembly",
        quantity=Decimal("20"),
        unit="PC",
        start_date=timezone.localdate() + timedelta(days=3),
        synced_at=now,
    )
    for item, material, description, required, unit in [
        ("0010", "RM-100", "Steel bracket", "100", "PC"),
        ("0020", "RM-110", "Bolt M8", "100", "PC"),
        ("0030", "RM-120", "Primer paint", "2", "KG"),
    ]:
        Component.objects.create(
            order=order,
            item=item,
            material=material,
            description=description,
            required_quantity=Decimal(required),
            withdrawn_quantity=Decimal("0"),
            unit=unit,
        )
    for material, quantity, unit in [
        ("RM-100", "70", "PC"),
        ("RM-110", "104", "PC"),
        ("RM-120", "1500", "G"),
    ]:
        Stock.objects.create(
            plant="AUC1", material=material, quantity=Decimal(quantity), unit=unit, synced_at=now
        )
    make_user("pat", "Planner")
    make_user("viv", "Viewer")
    return ORDER


def row(page: Page, material: str):
    return page.get_by_role("row").filter(has_text=material)


def request(page: Page, material: str) -> None:
    row(page, material).get_by_role("button", name="Request").click()


def open_as(page: Page, live_server: LiveServer, username: str = "pat") -> None:
    page.set_viewport_size(DESKTOP)
    log_in(page, live_server, username, ORDER)


def test_send_updates_the_row_label_and_the_highlight_follows_the_panel(
    order_page, mock, live_server: LiveServer, page: Page
) -> None:
    """P-1, P-3: Request highlights the row; Send swaps the panel and the row's label."""
    open_as(page, live_server)
    request(page, "RM-100")

    expect(page.get_by_role("heading", name="Review requisition")).to_be_visible()
    expect(row(page, "RM-100")).to_have_attribute("aria-current", "true")
    expect(row(page, "RM-110")).not_to_have_attribute("aria-current", "true")
    expect(page.get_by_label("Quantity (order unit PC)")).to_have_value("30")
    screenshot(page, "review")

    page.get_by_role("button", name="Send requisition").click()

    expect(page.get_by_role("heading", name="PR sent")).to_be_visible()
    expect(page.locator("#side-panel").get_by_text("10000042")).to_be_visible()
    # The label replaced the button in the table: this proves the out-of-band swap.
    expect(row(page, "RM-100").get_by_role("button", name="PR sent")).to_be_visible()
    expect(row(page, "RM-100").get_by_role("button", name="Request")).to_have_count(0)
    expect(row(page, "RM-100")).to_have_attribute("aria-current", "true")
    assert len(mock.payloads) == 1
    screenshot(page, "pr-sent")

    page.get_by_role("button", name="Close").click()
    expect(page.get_by_role("heading", name="Requisition", exact=True)).to_be_visible()
    expect(row(page, "RM-100")).not_to_have_attribute("aria-current", "true")

    row(page, "RM-100").get_by_role("button", name="PR sent").click()
    expect(page.get_by_role("heading", name="PR sent")).to_be_visible()
    expect(row(page, "RM-100")).to_have_attribute("aria-current", "true")


def test_a_failed_send_shows_pr_failed_and_retry_goes_back_to_review(
    order_page, mock, live_server: LiveServer, page: Page
) -> None:
    """P-3, AC-21, AC-25 in the browser: the label becomes PR failed; Retry shows Review."""
    mock.error = "Property 'PurchasingGroup' is required (item 1)."
    open_as(page, live_server)
    request(page, "RM-100")
    page.get_by_role("button", name="Send requisition").click()

    expect(page.get_by_role("heading", name="PR failed")).to_be_visible()
    expect(page.locator("#side-panel").get_by_text(mock.error)).to_be_visible()
    expect(row(page, "RM-100").get_by_role("button", name="PR failed")).to_be_visible()
    page.get_by_text("Request and response").click()
    expect(page.locator("#side-panel pre").first).to_contain_text("RequestedQuantity")
    screenshot(page, "pr-failed")

    page.get_by_role("button", name="Retry").click()
    expect(page.get_by_role("heading", name="Review requisition")).to_be_visible()


def test_cancel_clears_the_panel_and_the_highlight(
    order_page, mock, live_server: LiveServer, page: Page
) -> None:
    """R2-1: Cancel (a button of a sibling form) resets the panel and no row stays selected."""
    open_as(page, live_server)
    request(page, "RM-110")
    expect(row(page, "RM-110")).to_have_attribute("aria-current", "true")

    page.get_by_role("button", name="Cancel").click()

    expect(page.get_by_role("heading", name="Requisition", exact=True)).to_be_visible()
    expect(page.locator("tr[aria-current]")).to_have_count(0)
    assert mock.payloads == []


def test_the_sent_to_sap_value_follows_the_quantity(
    order_page, mock, live_server: LiveServer, page: Page
) -> None:
    """P-5, decision 8: 0.25 KG is 250 G in the stock unit; an invalid value shows a dash."""
    open_as(page, live_server)
    request(page, "RM-120")
    sent = page.locator("#sent-to-sap")
    expect(sent).to_have_text("500.000 G")  # the prefill: 0.5 KG short

    page.get_by_label("Quantity (order unit KG)").fill("0.25")
    expect(sent).to_have_text("250.000 G")
    page.get_by_label("Quantity (order unit KG)").fill("abc")
    expect(sent).to_have_text("–")
    assert mock.payloads == []


def test_already_open_is_shown_in_the_panel(
    order_page, mock, live_server: LiveServer, page: Page
) -> None:
    """P-7, decision 2: a 409 is swapped into the panel (htmx skips 4xx by default)."""
    open_as(page, live_server)
    request(page, "RM-100")
    order = ProductionOrder.objects.get(number="1000123")
    other = make_user("other", "Planner")
    Requisition.objects.create(
        order=order,
        material="RM-100",
        items="0010",
        quantity_entered=Decimal("30"),
        unit_entered="PC",
        quantity_sent=Decimal("30"),
        unit_sent="PC",
        delivery_date=timezone.localdate(),
        status=Requisition.Status.SENT,
        pr_number="10000001",
        created_by=other,
    )

    page.get_by_role("button", name="Send requisition").click()

    expect(page.locator("#side-panel").get_by_text("is already open (REQ-")).to_be_visible()
    expect(page.get_by_role("heading", name="Review requisition")).to_be_visible()
    assert mock.payloads == []


def test_a_viewer_sees_no_request_button_but_can_open_an_outcome(
    order_page, mock, live_server: LiveServer, page: Page
) -> None:
    """P-4, P-8: no Request or Retry for a Viewer; the label still opens the outcome."""
    order = ProductionOrder.objects.get(number="1000123")
    Requisition.objects.create(
        order=order,
        material="RM-100",
        items="0010",
        quantity_entered=Decimal("30"),
        unit_entered="PC",
        quantity_sent=Decimal("30"),
        unit_sent="PC",
        delivery_date=timezone.localdate(),
        status=Requisition.Status.FAILED,
        error_message="SAP says no.",
        created_by=make_user("other", "Planner"),
    )
    open_as(page, live_server, "viv")

    expect(page.get_by_role("button", name="Request")).to_have_count(0)
    expect(page.get_by_text("You can view requisitions but not create them.")).to_be_visible()
    row(page, "RM-100").get_by_role("button", name="PR failed").click()

    expect(page.get_by_role("heading", name="PR failed")).to_be_visible()
    expect(page.get_by_role("button", name="Retry")).to_have_count(0)
