"""Views handle the HTTP request and render a template.

Keep business logic out of here: put it in `cockpit/services/` and call it.
Every view needs a login (middleware) and declares its role check with `@requires(...)`.
"""

from django.contrib import messages
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth.views import LogoutView
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from cockpit.services.roles import Action, Role, can, role_of

LOGGED_OUT_MESSAGE = "You are logged out."


def home(request: HttpRequest) -> HttpResponse:
    """Send Admin to user administration; show business roles the start page.

    Until the orders page exists (#25) this is a placeholder; #25 makes it redirect to /orders/.
    """
    if role_of(request.user) is Role.ADMIN:
        return redirect("admin:index")
    if not can(request.user, Action.VIEW_BUSINESS):
        raise PermissionDenied
    return render(request, "cockpit/home.html")


# `home` cannot use @requires because Admin is redirected before the check. This marks it for
# the test that checks every cockpit URL has a role check (AC-44).
home.required_action = Action.VIEW_BUSINESS


def _render_denied(request: HttpRequest) -> HttpResponse:
    """Render the 403 page (ui-spec 4.7 E) for the current user."""
    # A CSRF failure can happen before the login middleware has set request.user.
    user = getattr(request, "user", None) or AnonymousUser()
    role = role_of(user)
    context = {
        "logged_in": user.is_authenticated,
        "role": role,
        "is_admin": role is Role.ADMIN,
    }
    return render(request, "403.html", context, status=403)


def permission_denied(request: HttpRequest, exception: Exception | None = None) -> HttpResponse:
    """The 403 handler (`handler403`): any refused page or action ends here."""
    return _render_denied(request)


def csrf_failure(request: HttpRequest, reason: str = "") -> HttpResponse:
    """CSRF_FAILURE_VIEW: a form or direct POST without a valid token gets the same 403 page."""
    return _render_denied(request)


class CockpitLogoutView(LogoutView):
    """Django's logout (POST only), followed by the message `You are logged out.`."""

    def post(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        response = super().post(request, *args, **kwargs)
        # Added after logout has cleared the session; the message travels in a cookie.
        messages.info(request, LOGGED_OUT_MESSAGE)
        return response
