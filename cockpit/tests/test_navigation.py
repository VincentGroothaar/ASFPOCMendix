"""The sidebar per role (ui-spec 2.2, AC-45, AC-46)."""

from unittest import mock

import pytest
from django.contrib.auth.models import AnonymousUser

from cockpit.services import navigation
from cockpit.services.navigation import pending_approval_count, sidebar_items


def labels(items) -> list[str]:
    return [item.label for item in items]


@pytest.mark.parametrize("role", ["Viewer", "Planner"])
def test_viewer_and_planner_see_orders_dashboard_requisitions(make_user, role) -> None:
    assert labels(sidebar_items(make_user(role), "/")) == ["Orders", "Dashboard", "Requisitions"]


def test_manager_also_sees_thresholds(make_user) -> None:
    items = sidebar_items(make_user("Manager"), "/")

    assert labels(items) == ["Orders", "Dashboard", "Requisitions", "Thresholds"]
    assert [item.url for item in items] == [
        "/orders/",
        "/dashboard/",
        "/requisitions/",
        "/settings/",
    ]


@pytest.mark.parametrize("groups", [("Admin",), (), ("Viewer", "Planner")])
def test_admin_and_users_without_a_role_get_no_items(make_user, groups) -> None:
    assert sidebar_items(make_user(*groups), "/") == []


def test_anonymous_gets_no_items() -> None:
    assert sidebar_items(AnonymousUser(), "/") == []


@pytest.mark.parametrize(
    ("path", "active"),
    [
        ("/orders/", "Orders"),
        ("/orders/1000123/", "Orders"),
        ("/requisitions/16/", "Requisitions"),
        ("/settings/", "Thresholds"),
        ("/", None),
    ],
)
def test_the_current_page_is_active(make_user, path, active) -> None:
    items = sidebar_items(make_user("Manager"), path)

    assert [item.label for item in items if item.active] == ([active] if active else [])


def test_the_approval_count_is_0_until_32(make_user) -> None:
    assert pending_approval_count(make_user("Manager")) == 0


def test_only_the_manager_gets_the_badge_count(make_user) -> None:
    with mock.patch.object(navigation, "pending_approval_count", return_value=3):
        manager = sidebar_items(make_user("Manager"), "/")
        planner = sidebar_items(make_user("Planner"), "/")

    assert [(i.label, i.badge_count) for i in manager if i.badge_count] == [("Requisitions", 3)]
    assert all(item.badge_count == 0 for item in planner)
