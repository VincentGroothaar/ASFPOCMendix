"""Roles and what each role may do (REQ-7, REQUIREMENTS.md "Business rules").

A user's role is the one role group they are in. The table below is the only place that says
what a role may do; group permissions in the database are not used. In Mendix terms: these are
the user roles and their module role access, fixed in the model instead of editable at runtime.
"""

from enum import StrEnum

from django.contrib.auth.models import AbstractBaseUser, AnonymousUser


class Role(StrEnum):
    """The four roles. The value is the name of the matching Django group."""

    VIEWER = "Viewer"
    PLANNER = "Planner"
    MANAGER = "Manager"
    ADMIN = "Admin"


class Action(StrEnum):
    """Something a user can try to do. Every cockpit view declares one with `requires`."""

    VIEW_BUSINESS = "view_business"
    CREATE_REQUISITION = "create_requisition"
    DECIDE_REQUISITION = "decide_requisition"
    CHANGE_SETTINGS = "change_settings"
    MANAGE_USERS = "manage_users"


# One row per role, copied from the permissions table in REQUIREMENTS.md. Nothing is inherited:
# each role lists every action it may do.
ROLE_ACTIONS: dict[Role, frozenset[Action]] = {
    Role.VIEWER: frozenset({Action.VIEW_BUSINESS}),
    Role.PLANNER: frozenset({Action.VIEW_BUSINESS, Action.CREATE_REQUISITION}),
    Role.MANAGER: frozenset(
        {
            Action.VIEW_BUSINESS,
            Action.CREATE_REQUISITION,
            Action.DECIDE_REQUISITION,
            Action.CHANGE_SETTINGS,
        }
    ),
    Role.ADMIN: frozenset({Action.MANAGE_USERS}),
}

ROLE_GROUP_NAMES: frozenset[str] = frozenset(role.value for role in Role)


def role_of(user: AbstractBaseUser | AnonymousUser) -> Role | None:
    """Return the user's role, or None when they have no usable role.

    A user has a role only when they are logged in, active, and in exactly one role group.
    Groups that are not role groups are ignored. Zero or several role groups means no role,
    so a broken account is locked out instead of getting more rights than intended.
    """
    if not user.is_authenticated or not user.is_active:
        return None
    role_names = [
        name for name in user.groups.values_list("name", flat=True) if name in ROLE_GROUP_NAMES
    ]
    if len(role_names) != 1:
        return None
    return Role(role_names[0])


def can(user: AbstractBaseUser | AnonymousUser, action: Action) -> bool:
    """True when the user's role allows the action."""
    role = role_of(user)
    return role is not None and action in ROLE_ACTIONS[role]
