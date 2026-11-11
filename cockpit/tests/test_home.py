"""Tests for the cockpit start page (`/`)."""

from pytest_django.asserts import assertContains, assertRedirects, assertTemplateUsed


def test_home_page_shows_app_name(client_as) -> None:
    response = client_as("Planner").get("/")

    assertContains(response, "<h1>Material Shortage Cockpit</h1>", html=True)
    assertTemplateUsed(response, "base.html")


def test_home_sends_admin_to_user_administration(client_as) -> None:
    response = client_as("Admin").get("/")

    assertRedirects(response, "/admin/")
