"""Browser checks for the order detail page (#26: D-3, D-9, AC-20 for Unit mismatch and Issued).

The snapshot is written straight into the database with a fresh `synced_at`, so the page never
calls SAP. Screenshots are saved under test-results/order-detail/ for the PR.
"""

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from django.utils import timezone
from playwright.sync_api import Page, expect
from pytest_django.live_server_helper import LiveServer

from cockpit.models import Component, PlantSnapshot, ProductionOrder, Stock
from tests.test_browser_ui import DESKTOP, NARROW, log_in, make_user

SCREENSHOTS = Path(__file__).resolve().parent.parent / "test-results" / "order-detail"


def screenshot(page: Page, name: str) -> None:
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SCREENSHOTS / f"{name}.png"), full_page=True)


@pytest.fixture
def order_page(transactional_db, settings) -> str:
    """Order 1000123 with one line of each status, like the wireframe; returns its path."""
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
        start_date=timezone.localdate() - timedelta(days=1),
        synced_at=now,
    )
    lines = [
        ("0010", "RM-100", "Steel bracket", "100", "PC", "0"),
        ("0020", "RM-110", "Bolt M8", "100", "PC", "0"),
        ("0030", "RM-120", "Primer paint", "2.5", "L", "0"),
        ("0040", "RM-130", "Polymer granulate", "12000", "G", "0"),
        ("0050", "RM-140", "Cable harness", "20", "M", "0"),
        ("0060", "RM-150", "Gasket", "4", "PC", "4"),
    ]
    for item, material, description, required, unit, withdrawn in lines:
        Component.objects.create(
            order=order,
            item=item,
            material=material,
            description=description,
            required_quantity=Decimal(required),
            withdrawn_quantity=Decimal(withdrawn),
            unit=unit,
        )
    for material, quantity, unit in [
        ("RM-100", "99", "PC"),
        ("RM-110", "100", "PC"),
        ("RM-120", "3200", "ML"),
        ("RM-130", "4", "KG"),
        ("RM-140", "35", "PC"),
    ]:
        Stock.objects.create(
            plant="AUC1",
            material=material,
            quantity=Decimal(quantity),
            unit=unit,
            synced_at=now,
        )
    make_user("viewer.a", "Viewer")
    return "/orders/1000123/"


def test_converted_stock_tooltip_opens_on_keyboard_focus(
    order_page, live_server: LiveServer, page: Page
) -> None:
    """D-9 and AC-13: `3.2 L` shows `3,200 ML (= 3.2 L)` on focus, hidden otherwise."""
    page.set_viewport_size(DESKTOP)
    log_in(page, live_server, "viewer.a", order_page)
    original = page.get_by_text("3,200 ML (= 3.2 L)", exact=True)
    expect(original).to_be_hidden()

    page.get_by_text("3.2 L", exact=True).focus()

    expect(original).to_be_visible()
    screenshot(page, "converted-stock-focus")


def test_header_mismatch_icon_and_overdue_pill(
    order_page, live_server: LiveServer, page: Page
) -> None:
    """D-3: the warning text shows on hover and on keyboard focus; Overdue ends the sub-line."""
    page.set_viewport_size(DESKTOP)
    log_in(page, live_server, "viewer.a", order_page)
    header = page.locator(".page-title")
    text = header.get_by_role("tooltip")
    icon = header.get_by_role("img", name="Unit mismatch: a component isn't checked")
    expect(text).to_be_hidden()

    icon.hover()
    expect(text).to_be_visible()
    page.mouse.move(0, 0)
    expect(text).to_be_hidden()
    icon.focus()
    expect(text).to_be_visible()

    expect(header.locator(".page-subline")).to_contain_text("Released")
    expect(header.locator(".page-subline .pill")).to_have_text("Overdue")


@pytest.mark.parametrize(
    ("status", "text"),
    [
        (
            "Unit mismatch",
            "Unit mismatch: order unit M and stock unit PC can't be converted, so this "
            "component isn't checked.",
        ),
        ("Issued", "Issued: no open requirement left, so it isn't checked."),
    ],
)
def test_mismatch_and_issued_tooltips(
    order_page, live_server: LiveServer, page: Page, status, text
) -> None:
    """AC-20 for the two statuses the acceptance test does not cover (ui-spec 5.2)."""
    log_in(page, live_server, "viewer.a", order_page)
    tooltip = page.get_by_text(text, exact=True)
    expect(tooltip).to_be_hidden()

    page.get_by_role("button", name=f"What does {status} mean?").focus()

    expect(tooltip).to_be_visible()


def test_screenshots_for_the_pr(order_page, live_server: LiveServer, page: Page) -> None:
    """The page as a Viewer (compare with docs/ui/screens/02-order-detail.png), wide and narrow."""
    page.set_viewport_size(DESKTOP)
    log_in(page, live_server, "viewer.a", order_page)
    screenshot(page, "order-detail")

    page.get_by_role("button", name="What does Short mean?").first.hover()
    screenshot(page, "order-detail-tooltip")

    page.set_viewport_size(NARROW)
    page.mouse.move(0, 0)
    width = page.evaluate("() => document.documentElement.scrollWidth")
    assert width <= NARROW["width"]
    screenshot(page, "order-detail-narrow")
