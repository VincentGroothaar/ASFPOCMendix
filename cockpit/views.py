"""Views handle the HTTP request and render a template.

Keep business logic out of here: put it in `cockpit/services/` and call it.
Every view needs a login (middleware) and declares its role check with `@requires(...)`.
"""

from dataclasses import dataclass
from decimal import Decimal
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth.views import LogoutView
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.cache import patch_vary_headers
from django.views.decorators.http import require_http_methods, require_POST

from cockpit.access import requires
from cockpit.services import requisitions
from cockpit.services.formats import format_datetime
from cockpit.services.order_list import (
    PILL_KEYS,
    OrderList,
    RequisitionFilter,
    build_order_list,
    default_filters,
    parse_filters,
    tile_tooltips,
)
from cockpit.services.roles import Action, Role, can, role_of
from cockpit.services.shortage import Status
from cockpit.services.sync import ensure_fresh, sync_plant

LOGGED_OUT_MESSAGE = "You are logged out."


def home(request: HttpRequest) -> HttpResponse:
    """Send Admin to user administration and business roles to the order list (#25)."""
    if role_of(request.user) is Role.ADMIN:
        return redirect("admin:index")
    if not can(request.user, Action.VIEW_BUSINESS):
        raise PermissionDenied
    return redirect("cockpit:order_list")


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


# --- Requisitions (REQ-5, #27) --------------------------------------------------------------------

# How the view answers each refusal from the requisition service.
REFUSAL_STATUS = {"unknown": 404, "not_requestable": 400, "invalid_quantity": 200, "duplicate": 409}


@require_http_methods(["GET", "POST"])
@requires(Action.CREATE_REQUISITION)
def requisition_create(request: HttpRequest, number: str) -> HttpResponse:
    """Confirm step (GET) and create (POST) of a requisition for one order and material.

    A plain page for now; #28 shows the same view in the side panel. All rules are in
    `services/requisitions.py`.
    """
    material = request.GET.get("material", "")
    if request.method == "GET":
        try:
            prefill = requisitions.prepare(number, material)
        except requisitions.RequisitionRefused as refused:
            return _render_refusal(request, refused)
        return _render_confirm(request, prefill, quantity_value=_plain(prefill.quantity))

    raw_quantity = request.POST.get("quantity", "")
    try:
        requisition = requisitions.create(request.user, number, material, raw_quantity)
    except requisitions.RequisitionRefused as refused:
        if refused.reason not in ("invalid_quantity", "duplicate"):
            return _render_refusal(request, refused)
        try:
            prefill = requisitions.prepare(number, material)
        except requisitions.RequisitionRefused as refused_again:
            return _render_refusal(request, refused_again)
        status = REFUSAL_STATUS[refused.reason]
        field_error = refused.message if refused.reason == "invalid_quantity" else ""
        page_error = refused.message if refused.reason == "duplicate" else ""
        return _render_confirm(
            request, prefill, raw_quantity, field_error, page_error, status=status
        )
    retry_url = f"{request.path}?{urlencode({'material': material})}"
    return render(
        request,
        "cockpit/requisitions/result.html",
        {"requisition": requisition, "retry_url": retry_url},
    )


def _render_confirm(
    request: HttpRequest,
    prefill: requisitions.Prefill,
    quantity_value: str,
    error: str = "",
    refusal: str = "",
    status: int = 200,
) -> HttpResponse:
    """The confirm form, prefilled or with the value the planner typed and its error."""
    context = {
        "prefill": prefill,
        "quantity_value": quantity_value,
        "error": error,
        "refusal": refusal,
        "cover_percent": _plain(prefill.cover_percent),
    }
    return render(request, "cockpit/requisitions/confirm.html", context, status=status)


def _render_refusal(request: HttpRequest, refused: requisitions.RequisitionRefused) -> HttpResponse:
    """A page that says why this order and material cannot be requested."""
    status = REFUSAL_STATUS[refused.reason]
    return render(
        request, "cockpit/requisitions/refused.html", {"message": refused.message}, status=status
    )


def _plain(value: Decimal) -> str:
    """A number as a plain string without trailing zeros, for a form field: 30.000 → 30."""
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


# --- Orders (REQ-1, REQ-4; issue #25) -----------------------------------------------------------

# The Requisition select on the order list (ui-spec 4.1), in screen order.
REQUISITION_OPTIONS = [
    ("", "All"),
    (RequisitionFilter.NONE.value, "None"),
    (RequisitionFilter.SENT.value, "PR sent"),
    (RequisitionFilter.AWAITING_APPROVAL.value, "Awaiting approval"),
    (RequisitionFilter.FAILED.value, "PR failed"),
]
STATUS_TITLES = {
    None: "All orders",
    Status.SHORT: "Short orders",
    Status.LOW_COVER: "Low cover orders",
    Status.COVERED: "Covered orders",
}


@requires(Action.VIEW_BUSINESS)
def order_list(request: HttpRequest) -> HttpResponse:
    """The order list: filter bar, tiles and table (ui-spec 4.1).

    A filter change is an HTMX request: it gets only `#orders-results` plus the out-of-band
    header and filter-bar blocks. Every other request (also htmx's history restore) gets the
    full page (ARCHITECTURE.md, "HTMX on data pages").
    """
    plants = settings.COCKPIT_PLANTS
    today = timezone.localdate()
    filters = parse_filters(request.GET, plants, today)
    sync = ensure_fresh(filters.plant)
    requisition_value = filters.requisition.value if filters.requisition else ""
    context = {
        "filters": filters,
        "plants": plants,
        "sync": sync,
        "refresh_url": reverse("cockpit:refresh_plant", args=[filters.plant]),
        "reset_query": urlencode(
            default_filters(plants, today).query(
                status=filters.status, requisition=filters.requisition
            )
        ),
        "clear_query": urlencode(filters.query(status=None, requisition=None, page=1)),
        "requisition_options": REQUISITION_OPTIONS,
        "requisition_value": requisition_value,
        "requisition_title": dict(REQUISITION_OPTIONS)[requisition_value],
        "view_title": STATUS_TITLES[filters.status],
    }
    if sync.synced_at is not None:
        orders = build_order_list(filters, today)
        context["orders"] = orders
        context["tiles"] = _tiles(orders, filters.status)
        context["banner_text"] = (
            f"SAP could not be reached. Showing data as of {format_datetime(sync.synced_at)}."
        )

    is_fragment = request.headers.get("HX-Request") == "true" and not request.headers.get(
        "HX-History-Restore-Request"
    )
    template = "cockpit/orders/results.html" if is_fragment else "cockpit/orders/page.html"
    response = render(request, template, context)
    patch_vary_headers(response, ["HX-Request"])
    return response


@dataclass(frozen=True)
class Tile:
    """One KPI tile on the order list (ui-spec 3.4): a toggle for the status filter."""

    label: str
    count: int
    pill_key: str | None  # colour of the number; None for All orders
    pressed: bool
    value: str  # the `status` it sends; "" clears the filter (a pressed tile, or All orders)
    tooltip: str | None


def _tiles(orders: OrderList, selected: Status | None) -> list[Tile]:
    """The four tiles: All orders, Short, Low cover and Covered, with counts and tooltips."""
    tooltips = tile_tooltips(orders.buffer_percent)
    tiles = [Tile("All orders", orders.counts.all, None, selected is None, "", None)]
    for status, label, count in (
        (Status.SHORT, "Short", orders.counts.short),
        (Status.LOW_COVER, "Low cover", orders.counts.low_cover),
        (Status.COVERED, "Covered", orders.counts.covered),
    ):
        pressed = selected == status
        value = "" if pressed else status.value
        tiles.append(Tile(label, count, PILL_KEYS[status], pressed, value, tooltips[status]))
    return tiles


@requires(Action.VIEW_BUSINESS)
@require_POST
def refresh_plant(request: HttpRequest, plant: str) -> HttpResponse:
    """Refresh and Try again: sync the plant from SAP now, then reload the page (AC-4).

    The page header's Refresh posts here with HTMX; the answer `HX-Refresh: true` makes the
    browser reload the page with its own URL, so the filters stay (contract from #23).
    """
    if plant not in settings.COCKPIT_PLANTS:
        raise Http404("Unknown plant")
    sync_plant(plant)
    if request.headers.get("HX-Request") == "true":
        response = HttpResponse(status=204)
        response["HX-Refresh"] = "true"
        return response
    return redirect(f"{reverse('cockpit:order_list')}?{urlencode({'plant': plant})}")
