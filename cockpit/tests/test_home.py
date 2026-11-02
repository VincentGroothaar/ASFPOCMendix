"""Tests for the cockpit start page."""

from django.test import Client


def test_home_page_shows_app_name(client: Client) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "Material Shortage Cockpit" in response.content.decode()
    assert "base.html" in [template.name for template in response.templates]
