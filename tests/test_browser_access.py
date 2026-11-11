"""Browser tests: what a user sees when an HTMX request is refused or the session ended (#22).

They use the stand-in pages in cockpit/tests/access_urls.py. They prove the htmx config in
base.html works in a real browser: a 403 replaces the whole page even when the clicked
element asks for a different swap, and an expired session sends the browser to the login page
and back to where the user was.
"""

import pytest
from django.contrib.auth.models import Group, User
from playwright.sync_api import Page, expect
from pytest_django.live_server_helper import LiveServer

PASSWORD = "a-long-test-password-31"


@pytest.fixture
def viewer(transactional_db) -> User:
    user = User.objects.create_user("vera", password=PASSWORD)
    user.groups.add(Group.objects.get_or_create(name="Viewer")[0])
    return user


@pytest.fixture
def access_pages(settings) -> None:
    settings.ROOT_URLCONF = "cockpit.tests.access_urls"


def log_in(page: Page, live_server: LiveServer, path: str) -> None:
    """Open a page as vera through the real login form."""
    page.set_default_timeout(5_000)
    page.goto(live_server.url + path)
    page.get_by_label("Username").fill("vera")
    page.get_by_label("Password").fill(PASSWORD)
    page.get_by_role("button", name="Log in").click()


def test_a_refused_htmx_action_shows_the_full_403_page(
    access_pages, viewer, live_server: LiveServer, page: Page
) -> None:
    log_in(page, live_server, "/test/page/")
    expect(page.get_by_role("heading", name="Test page")).to_be_visible()

    # This button asks for hx-swap="outerHTML" and an hx-select that matches nothing.
    page.get_by_role("button", name="Forbidden action").click()

    expect(page.get_by_role("heading", name="You don't have permission for this")).to_be_visible()
    expect(page.get_by_text("You are logged in as Viewer.")).to_be_visible()
    expect(page.get_by_role("heading", name="Test page")).to_have_count(0)


def test_an_htmx_action_after_the_session_ended_goes_to_login_and_back(
    access_pages, viewer, live_server: LiveServer, page: Page
) -> None:
    log_in(page, live_server, "/test/page/?plant=AUC1")
    expect(page.get_by_role("heading", name="Test page")).to_be_visible()

    page.context.clear_cookies()
    page.get_by_role("button", name="Allowed action").click()

    page.wait_for_url("**/accounts/login/?next=%2Ftest%2Fpage%2F%3Fplant%3DAUC1")
    expect(page.get_by_role("button", name="Log in")).to_be_visible()

    page.get_by_label("Username").fill("vera")
    page.get_by_label("Password").fill(PASSWORD)
    page.get_by_role("button", name="Log in").click()

    page.wait_for_url("**/test/page/?plant=AUC1")
    expect(page.get_by_role("heading", name="Test page")).to_be_visible()
