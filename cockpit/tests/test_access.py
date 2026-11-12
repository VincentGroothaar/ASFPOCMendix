"""Tests for login and role checks on every page (REQ-7, INV-1, INV-9, AC-39, AC-41, AC-44)."""

from urllib.parse import quote

import pytest
from django.contrib.auth.models import Group
from django.test import Client
from django.urls import URLPattern, URLResolver, get_resolver
from pytest_django.asserts import assertContains, assertNotContains

from cockpit.services.roles import ROLE_ACTIONS, Role
from cockpit.tests.access_urls import STORED_GROUP_NAME

DENIED_TITLE = "You don't have permission for this"
NO_ROLE_TEXT = "Your account has no role. Ask an Admin to assign one."
LOGGED_OUT_TEXT = "Your session has expired or the form was out of date. Log in again."
HTMX = {"HTTP_HX_REQUEST": "true"}


def cockpit_views() -> list[tuple[str, object]]:
    """(route, view) for every URL of the cockpit app."""
    views = []
    for entry in get_resolver().url_patterns:
        if isinstance(entry, URLResolver) and entry.namespace == "cockpit":
            for pattern in entry.url_patterns:
                if isinstance(pattern, URLPattern):
                    views.append((str(pattern.pattern), pattern.callback))
    return views


# --- AC-44: every cockpit URL has a role check ----------------------------------------------------


def test_the_app_has_cockpit_urls_to_check() -> None:
    assert cockpit_views(), "the walker found no cockpit URLs; it would check nothing"


def test_every_cockpit_url_declares_its_role_check() -> None:
    unchecked = [route for route, view in cockpit_views() if not hasattr(view, "required_action")]

    assert unchecked == []


# --- Login is required (INV-9) --------------------------------------------------------------------


@pytest.mark.parametrize("method", ["get", "post"])
def test_anonymous_requests_are_sent_to_login(db, method) -> None:
    response = getattr(Client(), method)("/")

    assert response.status_code == 302
    assert response["Location"] == "/accounts/login/?next=/"


def test_the_login_page_is_public(db) -> None:
    assert Client().get("/accounts/login/").status_code == 200


def test_anonymous_htmx_request_redirects_the_whole_page_back_to_where_the_user_was(db) -> None:
    response = Client().get(
        "/", HTTP_HX_CURRENT_URL="http://testserver/orders/?plant=AUC1&page=2", **HTMX
    )

    assert response.status_code == 200
    assert response["HX-Redirect"] == "/accounts/login/?next=" + quote(
        "/orders/?plant=AUC1&page=2", safe=""
    )


@pytest.mark.parametrize(
    "current_url",
    ["https://evil.example/orders/", "javascript:alert(1)", None],
    ids=["other site", "script", "no header"],
)
def test_htmx_login_redirect_never_points_elsewhere(db, current_url) -> None:
    headers = dict(HTMX)
    if current_url is not None:
        headers["HTTP_HX_CURRENT_URL"] = current_url

    response = Client().get("/", **headers)

    assert response["HX-Redirect"] == "/accounts/login/"


# --- Role checks per view -------------------------------------------------------------------------


@pytest.mark.parametrize("role", list(Role))
def test_each_role_reaches_only_what_its_role_allows(client_as, role, settings) -> None:
    # No SAP connection: a data page then shows its "no data yet" state and never calls the
    # live sandbox from a unit test (#69, R-I3 on #25).
    settings.SAP_BASE_URL = ""
    client = client_as(role.value)

    for route, view in cockpit_views():
        if "<" in route:
            continue  # URLs with arguments get their own tests in the issue that adds them
        response = client.get("/" + route)
        if route == "" and role is Role.ADMIN:
            assert response["Location"] == "/admin/"
        elif route == "" and view.required_action in ROLE_ACTIONS[role]:
            assert response["Location"] == "/orders/"  # the start page is the order list (#25)
        elif view.required_action in ROLE_ACTIONS[role]:
            assert response.status_code == 200, route
        else:
            assert response.status_code == 403, route


@pytest.mark.parametrize(
    "groups", [(), ("Viewer", "Planner"), ("Coffee club",)], ids=["none", "two", "unknown"]
)
def test_a_user_without_a_usable_role_is_refused_everywhere(client_as, groups) -> None:
    client = client_as(*groups)

    response = client.get("/")
    assert response.status_code == 403
    assertContains(response, NO_ROLE_TEXT, status_code=403)
    assert client.get("/admin/")["Location"].startswith("/admin/login/")


@pytest.mark.parametrize("role", ["Viewer", "Admin"])
def test_a_forbidden_post_returns_403_and_stores_nothing(access_urls, client_as, role) -> None:
    response = client_as(role).post("/test/create/")

    assert response.status_code == 403
    assert not Group.objects.filter(name=STORED_GROUP_NAME).exists()


def test_an_allowed_post_does_store(access_urls, client_as) -> None:
    assert client_as("Planner").post("/test/create/").status_code == 200
    assert Group.objects.filter(name=STORED_GROUP_NAME).exists()


# --- The 403 page (AC-41) -------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["Viewer", "Planner", "Manager"])
def test_403_names_the_role_and_links_back_to_orders(access_urls, client_as, role) -> None:
    response = client_as(role).get("/test/forbidden/")

    assertContains(response, DENIED_TITLE, status_code=403)
    assertContains(
        response,
        f"You are logged in as {role}. This role cannot open this page or do this action.",
        status_code=403,
    )
    assertContains(
        response, '<a class="btn" href="/orders/">Back to orders</a>', html=True, status_code=403
    )


def test_403_for_admin_links_to_user_administration(access_urls, client_as) -> None:
    response = client_as("Admin").get("/test/page/")

    assertContains(response, "You are logged in as Admin.", status_code=403)
    assertContains(
        response,
        '<a class="btn" href="/admin/">Go to user administration</a>',
        html=True,
        status_code=403,
    )
    assertNotContains(response, "Back to orders", status_code=403)


def test_403_for_a_user_without_role_offers_log_out(client_as) -> None:
    response = client_as().get("/")

    assertContains(response, NO_ROLE_TEXT, status_code=403)
    assertContains(response, 'action="/accounts/logout/"', status_code=403)
    assertContains(response, "csrfmiddlewaretoken", status_code=403)
    assertNotContains(response, "Back to orders", status_code=403)


def test_403_on_an_htmx_request_is_the_full_page(access_urls, client_as) -> None:
    response = client_as("Viewer").get("/test/forbidden/", **HTMX)

    assert response.status_code == 403
    assertContains(response, '<div id="page">', status_code=403)
    assertContains(response, DENIED_TITLE, status_code=403)


def test_a_post_without_csrf_token_gets_the_403_page(make_user) -> None:
    client = Client(enforce_csrf_checks=True)
    client.force_login(make_user("Planner"))

    response = client.post("/accounts/logout/")

    assertContains(response, DENIED_TITLE, status_code=403)
    assertContains(response, "You are logged in as Planner.", status_code=403)


def test_a_stale_login_form_tells_a_logged_out_user_to_log_in_again(db) -> None:
    response = Client(enforce_csrf_checks=True).post(
        "/accounts/login/", {"username": "x", "password": "y"}
    )

    assertContains(response, LOGGED_OUT_TEXT, status_code=403)
    assertContains(
        response, '<a class="btn" href="/accounts/login/">Log in</a>', html=True, status_code=403
    )
    assertNotContains(response, NO_ROLE_TEXT, status_code=403)


def test_htmx_login_redirect_from_a_query_only_url_keeps_a_path(db) -> None:
    response = Client().get("/", HTTP_HX_CURRENT_URL="http://testserver?x=1", **HTMX)

    assert response["HX-Redirect"] == "/accounts/login/?next=" + quote("/?x=1", safe="")
