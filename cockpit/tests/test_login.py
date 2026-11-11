"""Tests for logging in and out (REQ-7, ui-spec 4.7 A, AC-42)."""

import pytest
from django.test import Client
from pytest_django.asserts import assertContains, assertRedirects

from cockpit.tests.conftest import PASSWORD


def test_login_page_shows_the_form_and_note(db) -> None:
    response = Client().get("/accounts/login/")

    assertContains(response, "Username")
    assertContains(response, "Password")
    assertContains(
        response, '<button class="btn btn-primary" type="submit">Log in</button>', html=True
    )
    assertContains(response, "Accounts and roles: Admin in Django admin.")


@pytest.mark.parametrize(("role", "landing"), [("Planner", "/"), ("Admin", "/admin/")])
def test_after_login_each_role_lands_on_its_start_page(make_user, role, landing) -> None:
    make_user(role, username="person")
    client = Client()

    response = client.post(
        "/accounts/login/", {"username": "person", "password": PASSWORD}, follow=True
    )

    assert response.redirect_chain[-1][0] == landing
    assert response.status_code == 200


def test_login_returns_to_the_page_asked_for(make_user) -> None:
    make_user("Viewer", username="person")

    response = Client().post(
        "/accounts/login/", {"username": "person", "password": PASSWORD, "next": "/requisitions/"}
    )

    assert response["Location"] == "/requisitions/"


def test_wrong_password_shows_an_error(make_user) -> None:
    make_user("Viewer", username="person")

    response = Client().post("/accounts/login/", {"username": "person", "password": "wrong"})

    assertContains(response, "Please enter a correct username and password.")


def test_logout_returns_to_login_with_a_message(client_as) -> None:
    client = client_as("Planner")

    response = client.post("/accounts/logout/", follow=True)

    assertRedirects(response, "/accounts/login/")
    assertContains(response, "You are logged out.")
    assert client.get("/")["Location"].startswith("/accounts/login/")


def test_logout_by_get_does_not_log_out(client_as) -> None:
    client = client_as("Planner")

    assert client.get("/accounts/logout/").status_code == 405
    assert client.get("/").status_code == 200
