"""The Django admin site, opened by role instead of by Django's staff flag (REQ-7).

Only users with the Admin role may use it. The staff flag and stored permissions are ignored,
so the role table in `cockpit/services/roles.py` is the only place that decides.
"""

from django.conf import settings
from django.contrib.admin import AdminSite
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.views import redirect_to_login
from django.http import HttpRequest, HttpResponse
from django.urls import reverse
from django.utils.decorators import method_decorator

from cockpit.services.roles import Action, can


class CockpitAdminSite(AdminSite):
    """Admin site for user administration only."""

    site_header = "Material Shortage Cockpit: user administration"
    site_title = "Cockpit user administration"
    index_title = "Users and roles"

    # Django's admin login form refuses users without the staff flag. The plain form has no
    # such check; `has_permission` below decides who may enter.
    login_form = AuthenticationForm

    def has_permission(self, request: HttpRequest) -> bool:
        """Only the Admin role may use the admin site."""
        return can(request.user, Action.MANAGE_USERS)

    @method_decorator(login_not_required)
    def login(self, request: HttpRequest, extra_context: dict | None = None) -> HttpResponse:
        """Send logged-out visitors to the cockpit login page, the one login page for everyone.

        Django sends logged-out visitors of some admin pages here and of others to LOGIN_URL;
        this makes it the same everywhere (#22). A logged-in user without the Admin role still
        sees the admin login page, which says they are not authorised. Logging in here by POST
        still works.
        """
        if request.method in ("GET", "HEAD") and not request.user.is_authenticated:
            next_url = request.GET.get(REDIRECT_FIELD_NAME) or reverse(
                "admin:index", current_app=self.name
            )
            return redirect_to_login(next_url, settings.LOGIN_URL)
        return super().login(request, extra_context)

    def logout(self, request: HttpRequest, extra_context: dict | None = None) -> HttpResponse:
        """Log out the same way as the rest of the cockpit: back to the login page."""
        from cockpit.views import CockpitLogoutView

        return CockpitLogoutView.as_view()(request)
