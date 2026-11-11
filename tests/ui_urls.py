"""A test-only URLconf: the app's own URLs plus a gallery of every shared UI component (#23).

The gallery shows the frame and components before the business pages exist. It is never
included in the app's own URLs; tests switch to it with `settings.ROOT_URLCONF`.
"""

from datetime import UTC, datetime

from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import path

from cockpit.access import requires
from cockpit.services.roles import Action
from config.urls import urlpatterns as app_urlpatterns

POST_OK_MARKER = "POST accepted by the server"

SHORT_TIP = (
    "Short: available stock is below the open requirement, after earlier orders take their share."
)
LOW_TIP = (
    "Low cover: covered, but less than 10% to spare (available below 110% of required). "
    "Nothing is reserved."
)
COVERED_TIP = "Covered: at least 10% to spare."


@requires(Action.VIEW_BUSINESS)
def gallery(request: HttpRequest) -> HttpResponse:
    """Every component with sample data (ui-spec 3)."""
    page = Paginator(list(range(120)), 50).page(1)
    context = {
        "synced_at": datetime(2026, 11, 2, 9, 2, tzinfo=UTC),
        "page_obj": page,
        "crumbs": [("Orders", "/orders/"), ("1000123", None)],
        "short_tip": SHORT_TIP,
        "low_tip": LOW_TIP,
        "covered_tip": COVERED_TIP,
        "summary": [
            ("Shortage", "6 PC", "short"),
            ("Requested", "6 PC"),
            ("Sent to SAP", "6.000 PC", "primary"),
        ],
        "steps": [
            ("done", "Requested", "planner.a · 02 Nov 10:11"),
            ("waiting", "Manager approval", "Waiting for a manager"),
            ("failed", "Sent to SAP", "SAP returned an error"),
            ("not_reached", "Sent to SAP", ""),
        ],
        "rows": [
            ("RM-100", "Steel bracket", "short", "Short", SHORT_TIP),
            ("RM-200", "Gasket set", "low", "Low cover", LOW_TIP),
            ("RM-COVER", "Cover plate", "covered", "Covered", COVERED_TIP),
        ],
    }
    return render(request, "testing/ui_gallery.html", context)


@requires(Action.VIEW_BUSINESS)
def post_ok(request: HttpRequest) -> HttpResponse:
    """An HTMX POST target that succeeds only with a valid CSRF token (AC-55)."""
    return HttpResponse(f'<p id="post-result">{POST_OK_MARKER}</p>')


@requires(Action.VIEW_BUSINESS)
def post_forbidden(request: HttpRequest) -> HttpResponse:
    """An HTMX POST target that is always refused, to trigger the full-page 403 swap."""
    raise PermissionDenied


urlpatterns = [
    path("test/ui/", gallery),
    path("test/ui/ok/", post_ok),
    path("test/ui/forbidden/", post_forbidden),
    *app_urlpatterns,
]

handler403 = "cockpit.views.permission_denied"
