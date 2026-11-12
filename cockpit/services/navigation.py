"""The sidebar items per role (ui-spec 2.2, D-15, D-29).

In Mendix terms: the navigation profile, with menu items shown per user role.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlencode

from django.contrib.auth.models import AbstractBaseUser, AnonymousUser

from cockpit.services.roles import Role, role_of

# The page URLs from spec.md "Pages and URLs". They 404 until their tickets land (#25 to #34).
ORDERS_URL = "/orders/"
DASHBOARD_URL = "/dashboard/"
REQUISITIONS_URL = "/requisitions/"
THRESHOLDS_URL = "/settings/"


@dataclass(frozen=True)
class NavItem:
    """One sidebar link."""

    label: str
    url: str
    icon: str
    active: bool = False
    badge_count: int = 0


# The URL parameters that Orders and the Dashboard share (#30): plant and start date range.
SHARED_PARAMS = ("plant", "from", "to")


def sidebar_items(
    user: AbstractBaseUser | AnonymousUser, current_path: str, query: str = ""
) -> list[NavItem]:
    """Return the sidebar links the user may see, with the current page marked active.

    Viewer and Planner: Orders, Dashboard, Requisitions. Manager: the same plus Thresholds,
    and a count badge on Requisitions. Admin, users without a role and anonymous users get
    no items: they have no business screens.

    `query` is the plant and range of the page being viewed (`plant=AUC1&from=...`). The Orders
    and Dashboard links carry it, so both screens keep the same plant and range (#30).
    """
    role = role_of(user)
    if role not in (Role.VIEWER, Role.PLANNER, Role.MANAGER):
        return []

    badge = pending_approval_count(user) if role is Role.MANAGER else 0
    links = [
        ("Orders", ORDERS_URL, "list", 0),
        ("Dashboard", DASHBOARD_URL, "grid", 0),
        ("Requisitions", REQUISITIONS_URL, "file", badge),
    ]
    if role is Role.MANAGER:
        links.append(("Thresholds", THRESHOLDS_URL, "sliders", 0))

    carried = {ORDERS_URL, DASHBOARD_URL}
    return [
        NavItem(
            label,
            f"{url}?{query}" if query and url in carried else url,
            icon,
            active=current_path.startswith(url),
            badge_count=count,
        )
        for label, url, icon, count in links
    ]


def shared_query(params: Mapping[str, str]) -> str:
    """The plant and range from the page's URL parameters, as a query string (may be empty)."""
    return urlencode({key: params[key] for key in SHARED_PARAMS if params.get(key)})


def pending_approval_count(user: AbstractBaseUser | AnonymousUser) -> int:
    """Requisitions awaiting approval that this Manager may decide (own requests excluded).

    Returns 0 until the approval rule exists: #32 replaces this with the real count.
    """
    return 0
