"""Browser checks for the frame and the shared components (#23: AC-45, AC-49, AC-52, AC-54, AC-55).

They use the test-only gallery in tests/ui_urls.py. Screenshots of the frame per role, the
login page, the 403 page and the gallery are saved under test-results/ui/ for the PR.
"""

from pathlib import Path
from unittest import mock

import pytest
from django.contrib.auth.models import Group, User
from playwright.sync_api import Page, expect
from pytest_django.live_server_helper import LiveServer

from cockpit.services import navigation
from tests.ui_urls import POST_OK_MARKER, SHORT_TIP

PASSWORD = "a-long-test-password-31"
SCREENSHOTS = Path(__file__).resolve().parent.parent / "test-results" / "ui"
DESKTOP = {"width": 1440, "height": 1000}
NARROW = {"width": 899, "height": 1000}


@pytest.fixture
def gallery_urls(settings) -> None:
    settings.ROOT_URLCONF = "tests.ui_urls"


def make_user(username: str, role: str) -> User:
    user = User.objects.create_user(username, password=PASSWORD)
    user.groups.add(Group.objects.get_or_create(name=role)[0])
    return user


def log_in(page: Page, live_server: LiveServer, username: str, path: str) -> None:
    page.set_default_timeout(5_000)
    page.goto(live_server.url + path)
    page.get_by_label("Username").fill(username)
    page.get_by_label("Password").fill(PASSWORD)
    page.get_by_role("button", name="Log in").click()
    page.wait_for_url(live_server.url + path)


def screenshot(page: Page, name: str) -> None:
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SCREENSHOTS / f"{name}.png"), full_page=True)


@pytest.mark.parametrize("role", ["Viewer", "Planner", "Manager"])
def test_frame_per_role(transactional_db, live_server: LiveServer, page: Page, role) -> None:
    make_user(f"{role.lower()}.a", role)
    page.set_viewport_size(DESKTOP)

    with mock.patch.object(navigation, "pending_approval_count", return_value=3):
        log_in(page, live_server, f"{role.lower()}.a", "/")

    nav = page.get_by_role("navigation", name="Main")
    expect(nav.get_by_role("link", name="Orders")).to_be_visible()
    expect(nav.get_by_role("link", name="Thresholds")).to_have_count(1 if role == "Manager" else 0)
    expect(nav.get_by_role("button", name="Log out")).to_be_visible()
    expect(nav.get_by_text("3", exact=True)).to_have_count(1 if role == "Manager" else 0)
    screenshot(page, f"frame-{role.lower()}")


def test_login_and_403_pages(
    gallery_urls, transactional_db, live_server: LiveServer, page: Page
) -> None:
    make_user("vera", "Viewer")
    page.set_viewport_size(DESKTOP)
    page.goto(live_server.url + "/accounts/login/")
    screenshot(page, "login")

    page.get_by_label("Username").fill("vera")
    page.get_by_label("Password").fill("wrong")
    page.get_by_role("button", name="Log in").click()
    expect(page.locator(".error-note")).to_be_visible()

    log_in(page, live_server, "vera", "/test/ui/")
    page.get_by_role("button", name="Post a forbidden action").click()
    expect(page.get_by_role("heading", name="You don't have permission for this")).to_be_visible()
    expect(page.get_by_role("navigation", name="Main")).to_be_visible()
    screenshot(page, "403-viewer")


def test_tooltip_opens_on_keyboard_focus_and_hover(
    gallery_urls, transactional_db, live_server: LiveServer, page: Page
) -> None:
    make_user("vera", "Viewer")
    page.set_viewport_size(DESKTOP)
    log_in(page, live_server, "vera", "/test/ui/")
    requests: list[str] = []
    page.on("request", lambda request: requests.append(request.url))

    tip = page.get_by_role("tooltip").filter(has_text=SHORT_TIP).last
    icon = page.get_by_role("button", name="What does Short mean?").last
    expect(tip).to_be_hidden()

    # Keyboard: Tab until the ⓘ in the components table has focus.
    page.locator("body").focus()
    for _ in range(80):
        page.keyboard.press("Tab")
        if icon.evaluate("el => el === document.activeElement"):
            break
    expect(icon).to_be_focused()
    expect(tip).to_be_visible()
    outline = icon.evaluate("el => getComputedStyle(el).outlineStyle")
    assert outline == "solid"  # visible focus outline (AC-54)

    icon.blur()
    expect(tip).to_be_hidden()

    icon.hover()
    expect(tip).to_be_visible()
    page.mouse.move(0, 0)
    expect(tip).to_be_hidden()

    assert requests == []  # the tooltip needs no request (AC-49)


def test_last_row_tooltip_is_not_clipped(
    gallery_urls, transactional_db, live_server: LiveServer, page: Page
) -> None:
    make_user("vera", "Viewer")
    page.set_viewport_size(DESKTOP)
    log_in(page, live_server, "vera", "/test/ui/")

    page.get_by_role("button", name="What does Covered mean?").last.focus()
    tip = page.get_by_role("tooltip").filter(has_text="Covered: at least 10% to spare.").last
    expect(tip).to_be_visible()

    # The point in the middle of the tooltip shows the tooltip itself, not a clipped card.
    box = tip.bounding_box()
    hit = page.evaluate(
        "([x, y]) => document.elementFromPoint(x, y).closest('[role=tooltip]') !== null",
        [box["x"] + box["width"] / 2, box["y"] + box["height"] - 2],
    )
    assert hit
    screenshot(page, "gallery")


def test_sizes_and_names(
    gallery_urls, transactional_db, live_server: LiveServer, page: Page
) -> None:
    make_user("vera", "Viewer")
    page.set_viewport_size(DESKTOP)
    log_in(page, live_server, "vera", "/test/ui/")

    heights = page.evaluate(
        """() => [...document.querySelectorAll('.sidebar-link, .btn')].map(el => ({
            compact: el.classList.contains('btn-compact'),
            height: el.getBoundingClientRect().height,
        }))"""
    )
    assert all(h["height"] >= (36 if h["compact"] else 44) for h in heights), heights
    info_heights = page.evaluate(
        "() => [...document.querySelectorAll('.info')].map(el => el.getBoundingClientRect().height)"
    )
    assert info_heights and all(h >= 36 for h in info_heights)
    unnamed = page.evaluate(
        """() => [...document.querySelectorAll('button, a')]
            .filter(el => !(el.innerText.trim() || el.getAttribute('aria-label')))
            .map(el => el.outerHTML)"""
    )
    assert unnamed == []


def test_narrow_screen_stacks_without_horizontal_scroll(
    gallery_urls, transactional_db, live_server: LiveServer, page: Page
) -> None:
    make_user("vera", "Viewer")
    page.set_viewport_size(NARROW)
    log_in(page, live_server, "vera", "/test/ui/")

    nav = page.get_by_role("navigation", name="Main").bounding_box()
    main = page.locator("main.content").bounding_box()
    assert nav["y"] + nav["height"] <= main["y"]  # sidebar above the content
    scroll = page.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")
    assert scroll <= 0
    assert page.locator(".table-scroll").evaluate("el => getComputedStyle(el).overflowX") == "auto"
    screenshot(page, "gallery-narrow")


def test_htmx_posts_carry_the_csrf_token_also_after_a_403_swap(
    gallery_urls, transactional_db, live_server: LiveServer, page: Page
) -> None:
    make_user("vera", "Viewer")
    page.set_viewport_size(DESKTOP)
    log_in(page, live_server, "vera", "/test/ui/")

    page.get_by_role("button", name="Post to the server").click()
    expect(page.get_by_text(POST_OK_MARKER)).to_be_visible()

    page.get_by_role("button", name="Post a forbidden action").click()
    expect(page.get_by_role("heading", name="You don't have permission for this")).to_be_visible()
    token = page.evaluate(
        "() => JSON.parse(document.body.getAttribute('hx-headers'))['X-CSRFToken']"
    )
    assert token

    # The swapped 403 page has no POST button: start a second POST from the page itself.
    page.evaluate("() => htmx.ajax('POST', '/test/ui/ok/', {target: '#page', swap: 'innerHTML'})")
    expect(page.get_by_text(POST_OK_MARKER)).to_be_visible()
