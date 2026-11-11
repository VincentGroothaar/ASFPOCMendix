"""Tests for user administration in Django admin, by role (REQ-7, AC-30, AC-40)."""

import pytest
from django.contrib.auth.models import Group, User
from django.test import Client
from pytest_django.asserts import assertContains, assertNotContains

from cockpit.admin import EXACTLY_ONE_ROLE, CockpitUserChangeForm
from cockpit.tests.conftest import PASSWORD


def role_group(name: str) -> Group:
    return Group.objects.get(name=name)


# --- Who can open the admin ---------------------------------------------------------------------


def test_admin_logs_in_through_the_admin_login_page(make_user) -> None:
    make_user("Admin", username="boss")
    client = Client()

    response = client.post("/admin/login/?next=/admin/", {"username": "boss", "password": PASSWORD})

    assert response.status_code == 302
    assert response["Location"] == "/admin/"
    index = client.get("/admin/")
    assertContains(index, "Users")
    assertContains(index, "Groups")


def test_a_viewer_who_logs_in_on_the_admin_page_still_cannot_use_it(make_user) -> None:
    make_user("Viewer", username="vera")
    client = Client()
    client.post("/admin/login/", {"username": "vera", "password": PASSWORD})

    response = client.get("/admin/auth/user/")

    assert response.status_code == 302
    assert response["Location"].startswith("/admin/login/")


def test_staff_flag_alone_does_not_open_the_admin(make_user) -> None:
    user = make_user("Planner")
    user.is_staff = True
    user.is_superuser = True
    user.save()
    client = Client()
    client.force_login(user)

    assert client.get("/admin/")["Location"].startswith("/admin/login/")


@pytest.mark.parametrize("path", ["/admin/", "/admin/auth/user/", "/admin/login/"])
def test_anonymous_admin_visitors_end_on_the_cockpit_login_page(db, path) -> None:
    response = Client().get(path, follow=True)

    final_url = response.redirect_chain[-1][0]
    assert final_url.startswith("/accounts/login/?next=/admin/"), final_url
    assertContains(response, "Accounts and roles: Admin in Django admin.")


def test_admin_logout_goes_back_to_the_cockpit_login(client_as) -> None:
    client = client_as("Admin")

    response = client.post("/admin/logout/")

    assert response["Location"] == "/accounts/login/"
    assert client.get("/admin/", follow=True).redirect_chain[-1][0].startswith("/accounts/login/")


# --- Exactly one role (AC-40) -------------------------------------------------------------------


def add_user_form(**roles) -> dict:
    return {
        "username": "newbie",
        "usable_password": "true",
        "password1": PASSWORD,
        "password2": PASSWORD,
        **roles,
    }


def test_add_user_with_one_role_creates_the_user_in_that_role(client_as) -> None:
    response = client_as("Admin").post(
        "/admin/auth/user/add/", add_user_form(groups=[role_group("Planner").pk])
    )

    assert response.status_code == 302
    assert list(User.objects.get(username="newbie").groups.values_list("name", flat=True)) == [
        "Planner"
    ]


@pytest.mark.parametrize("roles", [[], ["Viewer", "Manager"]], ids=["no role", "two roles"])
def test_add_user_without_exactly_one_role_is_refused(client_as, roles) -> None:
    form = add_user_form(groups=[role_group(name).pk for name in roles])

    response = client_as("Admin").post("/admin/auth/user/add/", form)

    assertContains(response, EXACTLY_ONE_ROLE)
    assert not User.objects.filter(username="newbie").exists()


@pytest.mark.parametrize("roles", [[], ["Viewer", "Manager"]], ids=["no role", "two roles"])
def test_change_user_without_exactly_one_role_is_refused(make_user, roles) -> None:
    user = make_user("Viewer")
    data = {
        "username": user.username,
        "is_active": "on",
        "date_joined": "2026-11-11 10:00:00",
        "groups": [role_group(name).pk for name in roles],
    }

    form = CockpitUserChangeForm(data=data, instance=user)

    assert not form.is_valid()
    assert form.errors["groups"] == [EXACTLY_ONE_ROLE]


def change_user_form(user: User, roles: list[str]) -> dict:
    """POST data for the admin's Change user page, as the browser sends it."""
    return {
        "username": user.username,
        "first_name": "",
        "last_name": "",
        "email": "",
        "is_active": "on",
        "groups": [role_group(name).pk for name in roles],
        "last_login_0": "",
        "last_login_1": "",
        "date_joined_0": "2026-11-11",
        "date_joined_1": "10:00:00",
    }


@pytest.mark.parametrize("roles", [[], ["Viewer", "Manager"]], ids=["no role", "two roles"])
def test_change_user_page_refuses_zero_or_two_roles(client_as, make_user, roles) -> None:
    user = make_user("Viewer")

    response = client_as("Admin").post(
        f"/admin/auth/user/{user.pk}/change/", change_user_form(user, roles)
    )

    assertContains(response, EXACTLY_ONE_ROLE)
    assert list(user.groups.values_list("name", flat=True)) == ["Viewer"]


def test_change_user_page_moves_a_user_to_another_role(client_as, make_user) -> None:
    user = make_user("Viewer", "Coffee club")

    response = client_as("Admin").post(
        f"/admin/auth/user/{user.pk}/change/", change_user_form(user, ["Manager"])
    )

    assert response.status_code == 302
    assert list(user.groups.values_list("name", flat=True)) == ["Manager"]


def test_only_role_groups_can_be_chosen(make_user) -> None:
    Group.objects.create(name="Coffee club")

    choices = {
        group.name
        for group in CockpitUserChangeForm(instance=make_user()).fields["groups"].queryset
    }

    assert choices == {"Viewer", "Planner", "Manager", "Admin"}


def test_user_form_hides_staff_superuser_and_permissions(client_as, make_user) -> None:
    user = make_user("Viewer")

    response = client_as("Admin").get(f"/admin/auth/user/{user.pk}/change/")

    assertContains(response, "Role")
    for hidden in ("is_staff", "is_superuser", "user_permissions"):
        assertNotContains(response, f'name="{hidden}"')


# --- Role groups are read only ------------------------------------------------------------------


def test_admin_can_view_role_groups(client_as) -> None:
    client = client_as("Admin")

    assert client.get("/admin/auth/group/").status_code == 200
    page = client.get(f"/admin/auth/group/{role_group('Viewer').pk}/change/")
    assert page.status_code == 200
    assertNotContains(page, 'name="name"')
    assertNotContains(page, 'name="permissions"')


def test_role_groups_cannot_be_added_renamed_or_deleted(client_as) -> None:
    client = client_as("Admin")
    viewer = role_group("Viewer")

    assert client.get("/admin/auth/group/add/").status_code == 403
    assert (
        client.post(f"/admin/auth/group/{viewer.pk}/change/", {"name": "Renamed"}).status_code
        == 403
    )
    assert client.post(f"/admin/auth/group/{viewer.pk}/delete/", {"post": "yes"}).status_code == 403
    assert Group.objects.filter(name="Viewer").exists()
