"""Smoke test: a real browser can open the app (issue #13).

This proves Playwright and its browser work, locally and in CI, before the HTMX flow
tests in tests/acceptance/ rely on them.
"""

from playwright.sync_api import Page, expect
from pytest_django.live_server_helper import LiveServer


def test_browser_opens_start_page(live_server: LiveServer, page: Page) -> None:
    page.goto(live_server.url)

    expect(page.get_by_role("heading", level=1)).to_have_text("Material Shortage Cockpit")
