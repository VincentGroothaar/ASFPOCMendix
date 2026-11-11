"""Access checks for views: the role check per view, and login for HTMX requests (REQ-7, INV-9).

Login itself is required for every view by `HtmxLoginRequiredMiddleware` (closed by default).
On top of that, every cockpit view says which action it performs with `@requires(...)`.
"""

from collections.abc import Callable
from functools import wraps
from urllib.parse import urlencode, urlsplit

from django.contrib.auth.middleware import LoginRequiredMiddleware
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import resolve_url
from django.utils.http import url_has_allowed_host_and_scheme

from cockpit.services.roles import Action, can


def requires(action: Action) -> Callable:
    """Decorate a view so it answers 403 unless the user's role allows `action`.

    The action is also stored on the view as `required_action`, so a test can check that no
    cockpit URL was left without a role check (AC-44).
    """

    def decorator(view: Callable) -> Callable:
        @wraps(view)
        def checked_view(request: HttpRequest, *args, **kwargs) -> HttpResponse:
            if not can(request.user, action):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        checked_view.required_action = action
        return checked_view

    return decorator


def page_before_htmx_request(request: HttpRequest) -> str | None:
    """Return the path and query of the page an HTMX request came from, or None.

    HTMX sends the browser's current URL in the HX-Current-URL header. It is only used when it
    points at this site, so the login page can never send someone to another site.
    """
    current_url = request.headers.get("HX-Current-URL", "")
    if not current_url:
        return None
    if not url_has_allowed_host_and_scheme(
        current_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return None
    parts = urlsplit(current_url)
    path = parts.path or "/"
    return f"{path}?{parts.query}" if parts.query else path


class HtmxLoginRequiredMiddleware(LoginRequiredMiddleware):
    """Django's LoginRequiredMiddleware, plus a whole-page redirect for HTMX requests.

    A normal request from a logged-out user is redirected to the login page as usual. An HTMX
    request instead gets an HX-Redirect header, so the browser loads the login page as a whole
    page instead of pasting it into a fragment. After login, the user returns to the page they
    were on, not to the fragment URL.
    """

    def handle_no_permission(self, request: HttpRequest, view_func: Callable) -> HttpResponse:
        if request.headers.get("HX-Request") != "true":
            return super().handle_no_permission(request, view_func)

        login_url = resolve_url(self.get_login_url(view_func))
        page = page_before_htmx_request(request)
        if page is not None:
            login_url = f"{login_url}?{urlencode({self.get_redirect_field_name(view_func): page})}"
        response = HttpResponse()
        response["HX-Redirect"] = login_url
        return response
