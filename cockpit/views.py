"""Views handle the HTTP request and render a template.

Keep business logic out of here: put it in `cockpit/services/` and call it.
Every view needs a login (middleware) and declares its role check with `@requires(...)`.
"""

from dataclasses import dataclass
from decimal import Decimal
from urllib.parse import urlencode, urlsplit

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth.views import LogoutView
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.cache import patch_vary_headers
from django.views.decorators.http import require_http_methods, require_POST

from cockpit.access import HtmxLoginRequiredMiddleware, requires
from cockpit.models import ORDER_NUMBER_LENGTH, ProductionOrder, Requisition
from cockpit.services import formats, plant_status, requisition_views, requisitions
from cockpit.services.dashboard import Dashboard, build_dashboard
from cockpit.services.formats import format_datetime
from cockpit.services.order_list import (
    PILL_KEYS,
    OrderList,
    RequisitionFilter,
    build_order_list,
    default_filters,
    latest_requisitions,
    material_descriptions,
    orders_in_scope,
    parse_filters,
    plant_result,
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


class NotFound(Http404):
    """A 404 with a title the user may see, e.g. `Order 1000123 not found` (#26, N-2).

    Any other 404 (an unknown URL, `get_object_or_404`) shows `Page not found`, because its
    message is technical (URL patterns, model names).
    """

    def __init__(self, title: str) -> None:
        super().__init__(title)
        self.title = title


PAGE_NOT_FOUND = "Page not found"


def page_not_found(request: HttpRequest, exception: Exception | None = None) -> HttpResponse:
    """The 404 handler (`handler404`).

    A logged-out user is sent to login first (N-1 on #26): the login middleware only runs for
    URLs that match a view, so an unknown URL would otherwise answer 404 without a login. The
    middleware's own method is reused, so an HTMX request gets `HX-Redirect` as everywhere else.
    """
    user = getattr(request, "user", None) or AnonymousUser()
    if not user.is_authenticated:
        middleware = HtmxLoginRequiredMiddleware(get_response=lambda request: HttpResponse())
        return middleware.handle_no_permission(request, page_not_found)
    title = exception.title if isinstance(exception, NotFound) else PAGE_NOT_FOUND
    return render(request, "404.html", {"title": title}, status=404)


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


# --- Requisition list and detail (REQ-5, #29) -----------------------------------------------------


@requires(Action.VIEW_BUSINESS)
def requisition_list(request: HttpRequest) -> HttpResponse:
    """All requisition attempts, newest first, with a Status filter and Only mine (ui-spec 4.4)."""
    result = requisition_views.list_requisitions(
        request.user,
        status=request.GET.get("status", ""),
        only_mine=request.GET.get("mine") == "1",
        page_number=request.GET.get("page", ""),
    )
    context = {
        "result": result,
        "page_obj": result.page,
        "status_filters": requisition_views.STATUS_FILTERS,
    }
    return render(request, "cockpit/requisitions/list.html", context)


@requires(Action.VIEW_BUSINESS)
def requisition_detail(request: HttpRequest, pk: int) -> HttpResponse:
    """One requisition: status, progress, details and, when sent or failed, technical details."""
    requisition = get_object_or_404(
        Requisition.objects.select_related("order", "created_by"), pk=pk
    )
    requisition_views.describe(requisition)
    summary = [
        (
            "Requested",
            formats.format_quantity(requisition.quantity_entered, requisition.unit_entered),
        ),
        (
            "Shortage when requested",
            formats.format_quantity(requisition.shortage_at_request, requisition.unit_entered)
            if requisition.shortage_at_request is not None
            else "–",
        ),
        ("Needed by", formats.format_date(requisition.delivery_date)),
    ]
    sub_parts = [
        requisition.material,
        requisition.description,
        requisition_views.pr_text(requisition),
    ]
    request_text, response_text = requisition_views.technical_details(requisition)
    context = {
        "requisition": requisition,
        "subline": " · ".join(part for part in sub_parts if part),
        "summary": summary,
        "breadcrumb_items": [
            ("Requisitions", reverse("cockpit:requisition_list")),
            (requisition.reference, None),
        ],
        "steps": requisition_views.requisition_timeline(requisition),
        "retry_url": requisition_views.retry_url(request.user, requisition),
        "show_technical": requisition_views.shows_technical_details(requisition),
        "request_text": request_text,
        "response_text": response_text,
    }
    return render(request, "cockpit/requisitions/detail.html", context)


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


# --- Dashboard (REQ-6, #30) ---------------------------------------------------------------------

DONUT_RADIUS = 15.9155  # a circle of circumference 100, so a slice's length is its percentage
DONUT_COLOURS = {
    "short": "var(--chart-short)",
    "low": "var(--chart-low)",
    "covered": "var(--chart-covered)",
    "mismatch": "var(--chart-mismatch)",
}


def _donut_segments(dashboard: Dashboard) -> list[dict[str, object]]:
    """The SVG ring segments of the donut: one circle per non-empty slice.

    Each segment is a dash of `length` (percent of the ring) at `offset`. A single slice at
    100% is a full ring, and a total of 0 has no segments (the template draws a grey ring).
    """
    segments = []
    start = 0.0
    for slice_ in dashboard.slices:
        if slice_.count == 0:
            continue
        length = 100 * slice_.count / dashboard.total
        segments.append(
            {
                "key": slice_.key,
                "colour": DONUT_COLOURS[slice_.key],
                "length": f"{length:.4f}",
                "gap": f"{100 - length:.4f}",
                "offset": f"{-start:.4f}",
            }
        )
        start += length
    return segments


def _donut_label(dashboard: Dashboard) -> str:
    """The text alternative of the donut, for screen readers."""
    parts = ", ".join(f"{s.count} {s.label.lower()}" for s in dashboard.slices)
    return f"{dashboard.total} orders: {parts}"


@requires(Action.VIEW_BUSINESS)
def dashboard(request: HttpRequest) -> HttpResponse:
    """The shortage dashboard for the same plant and range as Orders (ui-spec 4.3).

    Plant and range are changed on the Orders page; the sidebar carries them here. The
    states B, C and D (ui-spec 4.7) work as on Orders.
    """
    plants = settings.COCKPIT_PLANTS
    today = timezone.localdate()
    filters = parse_filters(request.GET, plants, today)
    sync = ensure_fresh(filters.plant)
    refresh_url = (
        reverse("cockpit:refresh_plant", args=[filters.plant])
        + "?"
        + urlencode({"next": request.get_full_path()})
    )
    context = {
        "filters": filters,
        "plants": plants,
        "sync": sync,
        "refresh_url": refresh_url,
        "choose_plant_url": f"{reverse('cockpit:order_list')}?"
        + urlencode({"plant": filters.plant, "filters": "open"}),
        "subline": (
            f"Plant {filters.plant} · start "
            f"{formats.format_date(filters.start_from)} – {formats.format_date(filters.start_to)}"
        ),
    }
    if sync.synced_at is not None:
        in_scope = orders_in_scope(filters, today)
        data = build_dashboard(
            in_scope,
            plant_result(filters.plant, today),
            latest_requisitions(in_scope),
            today,
            material_descriptions(in_scope),
        )
        context["dashboard"] = data
        context["segments"] = _donut_segments(data)
        context["donut_label"] = _donut_label(data)
        context["banner_text"] = (
            f"SAP could not be reached. Showing data as of {format_datetime(sync.synced_at)}."
        )
    return render(request, "cockpit/dashboard.html", context)


REFRESH_RETURN_PATHS = ("/orders/", "/dashboard/")
MAX_NEXT_LENGTH = 2000


def _safe_next(request: HttpRequest) -> str | None:
    """The page to return to after a Refresh without HTMX: only Orders or the dashboard."""
    target = request.POST.get("next") or request.GET.get("next") or ""
    if len(target) > MAX_NEXT_LENGTH or not target.startswith("/"):
        return None
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or parsed.path not in REFRESH_RETURN_PATHS:
        return None
    return target


@requires(Action.VIEW_BUSINESS)
def order_detail(request: HttpRequest, number: str) -> HttpResponse:
    """One order with its components, stock and statuses (ui-spec 4.2; issue #26).

    The order is looked up before the sync, because the plant to sync comes from the order; an
    unknown number never calls SAP. Orders are never deleted, so it still exists after the sync.
    """
    order = None
    if _storable_order_number(number):
        order = ProductionOrder.objects.filter(number=number).only("plant").first()
    if order is None:
        raise NotFound(f"Order {number} not found")
    sync = ensure_fresh(order.plant)
    detail = plant_status.order_detail(number, timezone.localdate())
    context = {
        "order": detail,
        "sync": sync,
        "refresh_url": reverse("cockpit:refresh_plant", args=[detail.plant]),
        "breadcrumb_items": [
            ("Orders", f"{reverse('cockpit:order_list')}?{urlencode({'plant': detail.plant})}"),
            (detail.number, None),
        ],
        "subline": _order_subline(detail),
        "pill_key": PILL_KEYS.get(detail.status) if detail.status else None,
    }
    if sync.failed and sync.synced_at is not None:
        context["banner_text"] = (
            f"SAP could not be reached. Showing data as of {format_datetime(sync.synced_at)}."
        )
    return render(request, "cockpit/orders/detail.html", context)


def _storable_order_number(number: str) -> bool:
    """False for a number the database cannot hold (too long, or a NUL byte), which would
    otherwise raise a database error (a 500) instead of a 404 (#77 review)."""
    return "\x00" not in number and len(number) <= ORDER_NUMBER_LENGTH


def _order_subline(detail: plant_status.OrderDetail) -> str:
    """`FG-210 · Pump assembly · Plant AUC1 · Start 03 Nov 2026 · 20 PC · Released` (ui-spec 4.2).

    An inactive order drops `Released` (decision 7 on #26).
    """
    parts = [
        detail.material,
        detail.description,
        f"Plant {detail.plant}",
        f"Start {formats.format_date(detail.start_date)}",
        formats.format_quantity(detail.quantity, detail.unit),
    ]
    if detail.is_active:
        parts.append("Released")
    return " · ".join(part for part in parts if part)


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
    target = _safe_next(request)
    if target:
        return redirect(target)
    return redirect(f"{reverse('cockpit:order_list')}?{urlencode({'plant': plant})}")
