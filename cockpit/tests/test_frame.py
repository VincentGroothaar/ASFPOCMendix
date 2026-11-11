"""The page frame per role, the login page and the 403 page in the frame (AC-45, AC-53, S-3)."""

import pytest
from django.template import RequestContext, Template
from django.test import Client, RequestFactory
from pytest_django.asserts import assertContains, assertInHTML, assertNotContains

from cockpit.tests.conftest import PASSWORD
from cockpit.views import csrf_failure


@pytest.mark.parametrize(
    ("role", "items"),
    [
        ("Viewer", ["Orders", "Dashboard", "Requisitions"]),
        ("Planner", ["Orders", "Dashboard", "Requisitions"]),
        ("Manager", ["Orders", "Dashboard", "Requisitions", "Thresholds"]),
    ],
)
def test_start_page_shows_the_frame_for_each_role(make_user, role, items) -> None:
    user = make_user(role, username=f"{role.lower()}.a")
    client = Client()
    client.force_login(user)

    response = client.get("/")

    assertContains(response, '<nav class="sidebar" aria-label="Main">')
    for label in items:
        assertContains(response, f"<span>{label}</span>")
    if role != "Manager":
        assertNotContains(response, "<span>Thresholds</span>")
    assertInHTML(f"<b>{role.lower()}.a</b>", response.content.decode())
    assertInHTML(f"<span>{role}</span>", response.content.decode())
    assertContains(response, 'action="/accounts/logout/"')
    assertContains(response, "<span>Log out</span>")


def test_the_403_page_for_a_user_without_a_role_has_a_sidebar_without_items(make_user) -> None:
    client = Client()
    client.force_login(make_user("Viewer", "Planner"))  # two roles = no usable role

    response = client.get("/")

    assertContains(response, '<nav class="sidebar" aria-label="Main">', status_code=403)
    assertNotContains(response, "<span>Orders</span>", status_code=403)


def test_the_403_page_for_a_viewer_has_the_sidebar_items(make_user, settings) -> None:
    settings.ROOT_URLCONF = "cockpit.tests.access_urls"
    client = Client()
    client.force_login(make_user("Viewer"))

    response = client.get("/test/forbidden/")

    assertContains(response, "You don't have permission for this", status_code=403)
    assertContains(response, "<span>Orders</span>", status_code=403)


def test_a_csrf_failure_without_a_user_still_renders_the_403_page() -> None:
    request = RequestFactory().post("/accounts/login/")
    assert not hasattr(request, "user")

    response = csrf_failure(request)

    assert response.status_code == 403
    assert b"Your session has expired" in response.content


def test_login_page_layout_and_wrong_password_error_note(make_user) -> None:
    make_user("Viewer", username="vera")

    response = Client().post("/accounts/login/", {"username": "vera", "password": "wrong"})

    assertContains(response, '<main class="login-page">')
    assertContains(response, '<form class="login-card"')
    assertContains(response, '<p class="error-note" role="alert">')
    assertNotContains(response, '<nav class="sidebar"')


def test_login_still_works(make_user) -> None:
    make_user("Planner", username="pia")

    response = Client().post("/accounts/login/", {"username": "pia", "password": PASSWORD})

    assert response.status_code == 302


def test_the_active_sidebar_item_has_aria_current(make_user) -> None:
    request = RequestFactory().get("/orders/1000123/")
    request.user = make_user("Manager")
    page = Template('{% extends "layouts/frame.html" %}').render(RequestContext(request))

    assert page.count('aria-current="page"') == 1
    assert 'href="/orders/" class="sidebar-link is-active" aria-current="page"' in page


def test_header_actions_render_in_the_page_header(make_user) -> None:
    request = RequestFactory().get("/")
    request.user = make_user("Manager")
    page = Template(
        '{% extends "layouts/frame.html" %}{% load ui %}'
        '{% block page_title %}{% page_header "REQ-16" "awaiting_approval" %}{% endblock %}'
        '{% block header_actions %}<button class="btn">Approve and send</button>{% endblock %}'
    ).render(RequestContext(request))

    header = page[page.index('<header class="page-header">') : page.index("</header>")]
    assert "<h1>REQ-16</h1>" in header
    actions = header[header.index('<div class="header-actions">') :]
    assert '<button class="btn">Approve and send</button>' in actions
