"""Smoke test: a real browser can open the app (issue #13).

This proves Playwright and its browser work, locally and in CI, before the HTMX flow
tests in tests/acceptance/ rely on them. Every page needs a login (#22), so the test logs
in through the real form first.
"""

import re

from django.contrib.auth.models import Group, User
from playwright.sync_api import Page, expect
from pytest_django.live_server_helper import LiveServer

PASSWORD = "a-long-test-password-31"


def test_browser_logs_in_and_opens_start_page(
    transactional_db, live_server: LiveServer, page: Page, settings
) -> None:
    settings.SAP_BASE_URL = ""  # the order list shows "no data yet"; no live SAP call
    planner = User.objects.create_user("pat", password=PASSWORD)
    planner.groups.add(Group.objects.get_or_create(name="Planner")[0])

    page.goto(live_server.url)
    expect(page).to_have_url(re.compile(r"/accounts/login/\?next=/$"))
    page.get_by_label("Username").fill("pat")
    page.get_by_label("Password").fill(PASSWORD)
    page.get_by_role("button", name="Log in").click()

    # The start page `/` is the order list (#25).
    expect(page).to_have_url(live_server.url + "/orders/")
    expect(page.get_by_role("heading", level=1)).to_have_text("Production orders")
    expect(page.get_by_label("Username")).to_have_count(0)
