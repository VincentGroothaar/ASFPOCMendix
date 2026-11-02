"""Tests for the cockpit start page."""

from django.test import Client
from pytest_django.asserts import assertContains, assertTemplateUsed


def test_home_page_shows_app_name(client: Client) -> None:
    response = client.get("/")

    assertContains(response, "<h1>Material Shortage Cockpit</h1>", html=True)
    assertTemplateUsed(response, "base.html")
