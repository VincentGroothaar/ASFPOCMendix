"""Tests for the cockpit start page (`/`): it sends each role to its first screen (#25)."""

from pytest_django.asserts import assertRedirects


def test_home_sends_business_roles_to_the_order_list(client_as) -> None:
    for role in ("Viewer", "Planner", "Manager"):
        response = client_as(role).get("/")

        assertRedirects(response, "/orders/", fetch_redirect_response=False)


def test_home_sends_admin_to_user_administration(client_as) -> None:
    response = client_as("Admin").get("/")

    assertRedirects(response, "/admin/")
