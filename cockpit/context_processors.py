"""Values every template gets, registered in settings.TEMPLATES."""

from django.contrib.auth.models import AnonymousUser
from django.http import HttpRequest

from cockpit.services.navigation import shared_query, sidebar_items
from cockpit.services.roles import role_of


def sidebar(request: HttpRequest) -> dict:
    """The sidebar links and the user's role for the page frame (ui-spec 2.2)."""
    # A CSRF failure can happen before the login middleware has set request.user.
    user = getattr(request, "user", None) or AnonymousUser()
    return {
        "sidebar_items": sidebar_items(user, request.path, shared_query(request.GET)),
        "user_role": role_of(user),
    }
