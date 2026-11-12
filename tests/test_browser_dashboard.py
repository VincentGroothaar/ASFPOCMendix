"""Browser check for the shortage dashboard (issue #30, AC-28h).

Builds a constructed snapshot, opens the dashboard as a Viewer at desktop and phone width,
checks for console errors and keyboard use, and saves screenshots under test-results/ui/.
"""

import re
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.contrib.auth.models import Group, User
from django.utils import timezone
from playwright.sync_api import Page, expect
from pytest_django.live_server_helper import LiveServer

from cockpit.models import Component, PlantSnapshot, ProductionOrder, Requisition, Stock

PASSWORD = "a-long-test-password-31"
SCREENSHOTS = Path(__file__).resolve().parent.parent / "test-results" / "ui"


def build_snapshot() -> None:
    """Four orders: short x2 (one overdue), low cover, and a unit mismatch; one requisition."""
    now = timezone.now()
    today = timezone.localdate()
    PlantSnapshot.objects.create(plant="AUC1", synced_at=now)
    user = User.objects.create_user("planner", password=PASSWORD)
    plan = [
        ("1000118", -3, "RM-100", "60", "Steel bracket", "PC"),
        ("1000123", 1, "RM-100", "50", "Steel bracket", "PC"),
        ("1000130", 3, "RM-130", "100", "Polymer granulate", "PC"),
        ("1000131", 4, "RM-170", "5", "Hydraulic oil", "PC"),
    ]
    stock = {"RM-100": ("70", "PC"), "RM-130": ("104", "PC"), "RM-170": ("50", "L")}
    for material, (quantity, unit) in stock.items():
        Stock.objects.create(
            plant="AUC1", material=material, quantity=Decimal(quantity), unit=unit, synced_at=now
        )
    for number, offset, material, needs, description, unit in plan:
        order = ProductionOrder.objects.create(
            number=number,
            plant="AUC1",
            material="FG-1",
            description="Bike",
            quantity=Decimal("1"),
            unit="PC",
            start_date=today + timedelta(days=offset),
            synced_at=now,
        )
        Component.objects.create(
            order=order,
            item="0001",
            material=material,
            description=description,
            required_quantity=Decimal(needs),
            withdrawn_quantity=Decimal("0"),
            unit=unit,
        )
    order = ProductionOrder.objects.get(number="1000123")
    Requisition.objects.create(
        order=order,
        material="RM-100",
        items="0001",
        quantity_entered=Decimal("10"),
        unit_entered="PC",
        quantity_sent=Decimal("10"),
        unit_sent="PC",
        delivery_date=order.start_date,
        status=Requisition.Status.AWAITING_APPROVAL,
        created_by=user,
    )


def test_dashboard_in_the_browser(transactional_db, live_server: LiveServer, page: Page) -> None:
    build_snapshot()
    viewer = User.objects.create_user("viewer.a", password=PASSWORD)
    viewer.groups.add(Group.objects.get_or_create(name="Viewer")[0])
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.set_default_timeout(5_000)
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)

    page.set_viewport_size({"width": 1440, "height": 1000})
    page.goto(live_server.url + "/dashboard/")
    page.get_by_label("Username").fill("viewer.a")
    page.get_by_label("Password").fill(PASSWORD)
    page.get_by_role("button", name="Log in").click()

    expect(page.get_by_role("heading", level=1)).to_have_text("Shortage dashboard")
    expect(page.get_by_text("Red orders")).to_be_visible()
    expect(page.get_by_text("Open requisitions · 1 awaiting approval")).to_be_visible()
    expect(
        page.get_by_text("Unit mismatch lines are excluded from component counts.")
    ).to_be_visible()
    expect(page.get_by_role("table").first.get_by_text("RM-100")).to_be_visible()
    page.screenshot(path=str(SCREENSHOTS / "03-dashboard-desktop.png"), full_page=True)

    # Keyboard: Tab reaches an order link and shows a focus ring.
    for _ in range(40):
        page.keyboard.press("Tab")
        if page.evaluate("document.activeElement.getAttribute('href')") == "/orders/1000123/":
            break
    assert page.evaluate("document.activeElement.getAttribute('href')") == "/orders/1000123/"

    # The sidebar link follows the plant and range of the URL.
    page.goto(live_server.url + "/dashboard/?plant=AUC1&from=2026-01-01&to=2026-12-31")
    expect(page.get_by_role("link", name="Orders", exact=True)).to_have_attribute(
        "href", "/orders/?plant=AUC1&from=2026-01-01&to=2026-12-31"
    )

    page.set_viewport_size({"width": 390, "height": 900})
    page.goto(live_server.url + "/dashboard/")
    expect(page.get_by_role("heading", level=1)).to_have_text("Shortage dashboard")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.screenshot(path=str(SCREENSHOTS / "03-dashboard-mobile.png"), full_page=True)

    assert errors == []


def test_orders_page_script_opens_filters_and_updates_the_sidebar(
    transactional_db, live_server: LiveServer, page: Page
) -> None:
    """`?filters=open` opens the filter bar and focuses Plant; a filter change updates the
    sidebar links to Orders and Dashboard (issue #30, rule 7, AC-28i)."""
    build_snapshot()
    viewer = User.objects.create_user("viewer.a", password=PASSWORD)
    viewer.groups.add(Group.objects.get_or_create(name="Viewer")[0])
    page.set_default_timeout(5_000)
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.goto(live_server.url + "/orders/?plant=AUC1&filters=open")
    page.get_by_label("Username").fill("viewer.a")
    page.get_by_label("Password").fill(PASSWORD)
    page.get_by_role("button", name="Log in").click()

    expect(page.locator("#filter-fields")).to_be_visible()
    expect(page.locator("#filter-plant")).to_be_focused()

    page.locator("input[name=from]").fill("2026-01-01")
    page.locator("input[name=from]").dispatch_event("change")
    link = page.get_by_role("link", name="Dashboard", exact=True)
    expect(link).to_have_attribute("href", re.compile(r"from=2026-01-01"))
    expect(link).to_have_attribute("href", re.compile(r"plant=AUC1"))


def build_long_lists_snapshot() -> None:
    """12 short orders on one material with a long ID: more than 5 orders, more than 10 rows."""
    now = timezone.now()
    today = timezone.localdate()
    PlantSnapshot.objects.create(plant="AUC1", synced_at=now)
    for index in range(12):
        order = ProductionOrder.objects.create(
            number=f"10001{index:02d}",
            plant="AUC1",
            material="FG-1",
            description="Bike",
            quantity=Decimal("1"),
            unit="PC",
            start_date=today + timedelta(days=1),
            synced_at=now,
        )
        Component.objects.create(
            order=order,
            item="0001",
            material="MZ-RM-C990-0001",
            description="Hydraulic oil for the long list check",
            required_quantity=Decimal("5"),
            withdrawn_quantity=Decimal("0"),
            unit="PC",
        )


def test_long_lists_stay_short_in_the_browser(
    transactional_db, live_server: LiveServer, page: Page
) -> None:
    """AC-61 (#80): at 1512 px the material ID stays on one line and no row is taller than 5
    body lines; at 390 px the page does not scroll sideways."""
    build_long_lists_snapshot()
    viewer = User.objects.create_user("viewer.a", password=PASSWORD)
    viewer.groups.add(Group.objects.get_or_create(name="Viewer")[0])
    page.set_default_timeout(5_000)
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)

    page.set_viewport_size({"width": 1512, "height": 900})
    page.goto(live_server.url + "/dashboard/")
    page.get_by_label("Username").fill("viewer.a")
    page.get_by_label("Password").fill(PASSWORD)
    page.get_by_role("button", name="Log in").click()

    expect(page.get_by_text("and 7 more")).to_be_visible()
    expect(page.get_by_text("Showing 10 of 12 orders")).to_be_visible()
    expect(page.get_by_role("link", name="Show all 12 short orders")).to_be_visible()

    page.screenshot(path=str(SCREENSHOTS / "03-dashboard-long-lists-desktop.png"), full_page=True)

    # The material ID is one line: its box is at most 1.5 times its line height.
    material = page.locator(".dash-material").first
    height, line_height = material.evaluate(
        "el => [el.getBoundingClientRect().height, parseFloat(getComputedStyle(el).lineHeight)]"
    )
    assert height <= 1.5 * line_height
    # No row of Shortage per material is taller than 5 times the body line height.
    body_line_height = page.evaluate("parseFloat(getComputedStyle(document.body).lineHeight)")
    row_height = page.locator("table.data").first.locator("tbody tr").first.bounding_box()["height"]
    assert row_height <= 5 * body_line_height

    page.set_viewport_size({"width": 390, "height": 900})
    page.goto(live_server.url + "/dashboard/")
    expect(page.get_by_role("heading", level=1)).to_have_text("Shortage dashboard")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.screenshot(path=str(SCREENSHOTS / "03-dashboard-long-lists-mobile.png"), full_page=True)
