"""Tests for the role table and how a user's role is found (REQ-7, AC-39)."""

import pytest
from django.contrib.auth.models import AnonymousUser

from cockpit.services.roles import ROLE_ACTIONS, Action, Role, can, role_of

# The permissions table from REQUIREMENTS.md "Business rules", written out by hand so a change
# to the code table has to be a deliberate change to this test too.
EXPECTED = {
    Role.VIEWER: {Action.VIEW_BUSINESS},
    Role.PLANNER: {Action.VIEW_BUSINESS, Action.CREATE_REQUISITION},
    Role.MANAGER: {
        Action.VIEW_BUSINESS,
        Action.CREATE_REQUISITION,
        Action.DECIDE_REQUISITION,
        Action.CHANGE_SETTINGS,
    },
    Role.ADMIN: {Action.MANAGE_USERS},
}


def test_role_table_matches_the_requirements() -> None:
    assert {role: set(actions) for role, actions in ROLE_ACTIONS.items()} == EXPECTED


def test_admin_has_no_business_actions_and_business_roles_cannot_manage_users() -> None:
    assert Action.VIEW_BUSINESS not in ROLE_ACTIONS[Role.ADMIN]
    for role in (Role.VIEWER, Role.PLANNER, Role.MANAGER):
        assert Action.MANAGE_USERS not in ROLE_ACTIONS[role]


@pytest.mark.parametrize("role", list(Role))
def test_one_role_group_gives_that_role(make_user, role) -> None:
    assert role_of(make_user(role.value)) is role


def test_an_extra_group_that_is_not_a_role_is_ignored(make_user) -> None:
    assert role_of(make_user("Planner", "Coffee club")) is Role.PLANNER


@pytest.mark.parametrize(
    "groups",
    [(), ("Viewer", "Manager"), ("Planner", "Admin"), ("Coffee club",)],
    ids=["no groups", "two roles", "role and admin", "only unknown groups"],
)
def test_zero_or_several_roles_means_no_role(make_user, groups) -> None:
    user = make_user(*groups)

    assert role_of(user) is None
    assert not any(can(user, action) for action in Action)


def test_an_inactive_user_has_no_role(make_user) -> None:
    assert role_of(make_user("Manager", is_active=False)) is None


def test_an_anonymous_user_has_no_role() -> None:
    assert role_of(AnonymousUser()) is None
    assert not can(AnonymousUser(), Action.VIEW_BUSINESS)
