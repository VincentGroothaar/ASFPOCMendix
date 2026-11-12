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
from cockpit.models import ProductionOrder, Requisition
from cockpit.services import (
    formats,
    order_panel,
    plant_status,
    requisition_views,
    requisitions,
)
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


# --- Requisitions and the side panel (REQ-5, #27, #28) ----------------------------------------

# How the view answers each refusal from the requisition service.
REFUSAL_STATUS = {"unknown": 404, "not_requestable": 400, "invalid_quantity": 200, "duplicate": 409}
PANEL_DIR = "cockpit/orders/panel"


def _is_htmx(request: HttpRequest) -> bool:
    """True for an HTMX request that wants a fragment (not htmx's history restore)."""
    return request.headers.get("HX-Request") == "true" and not request.headers.get(
        "HX-History-Restore-Request"
    )


def _render_panel(
    request: HttpRequest,
    number: str,
    state: str,
    panel: dict[str, object] | None = None,
    material: str = "",
    status: int = 200,
) -> HttpResponse:
    """Show the side panel in `state` (a template in `panel/`), with `material`'s rows selected.

    An HTMX request gets the panel plus the components rows (an out-of-band swap, so the
    highlight and the labels follow). Any other request gets the whole order page with the
    panel in the same state, so every panel URL also works without JavaScript (#28, I-2).
    """
    context = {"panel_template": f"{PANEL_DIR}/{state}.html", **(panel or {})}
    if _is_htmx(request):
        context.update(_rows_context(request, number, material))
        response = render(request, "cockpit/orders/panel_fragment.html", context, status=status)
    else:
        context.update(_order_page_context(request, number, material))
        response = render(request, "cockpit/orders/detail.html", context, status=status)
    patch_vary_headers(response, ["HX-Request"])
    return response


def _review_panel(
    request: HttpRequest,
    number: str,
    material: str,
    quantity_value: str | None = None,
    error: str = "",
    refusal: str = "",
    status: int = 200,
) -> HttpResponse:
    """The Review state: prefilled, or with the value the planner typed and its message."""
    try:
        prefill = requisitions.prepare(number, material)
    except requisitions.RequisitionRefused as refused:
        return _refusal_panel(request, number, material, refused)
    panel = {
        "prefill": prefill,
        "quantity_value": _plain(prefill.quantity) if quantity_value is None else quantity_value,
        "error": error,
        "refusal": refusal,
        "cover_percent": _plain(prefill.cover_percent),
        "sent": (prefill.quantity_sent, prefill.stock_unit),
    }
    return _render_panel(request, number, "review", panel, material, status)


def _refusal_panel(
    request: HttpRequest, number: str, material: str, refused: requisitions.RequisitionRefused
) -> HttpResponse:
    """Why this order and material cannot be requested: an error note in the panel (400)."""
    if refused.reason == "unknown":
        raise Http404(refused.message)
    panel = {"message": refused.message}
    return _render_panel(request, number, "error", panel, material, REFUSAL_STATUS[refused.reason])


def _outcome_panel(request: HttpRequest, requisition: Requisition) -> HttpResponse:
    """The outcome of one requisition: PR sent, PR failed, or another status (#32, #33)."""
    state = {"sent": "sent", "failed": "failed"}.get(requisition.status, "other")
    requisition_views.describe(requisition)
    request_text, response_text = requisition_views.technical_details(requisition)
    panel = {
        "requisition": requisition,
        "retry_url": requisition_views.retry_url(request.user, requisition),
        "request_text": request_text,
        "response_text": response_text,
    }
    return _render_panel(request, requisition.order.number, state, panel, requisition.material)


@require_http_methods(["GET", "POST"])
@requires(Action.CREATE_REQUISITION)
def requisition_create(request: HttpRequest, number: str) -> HttpResponse:
    """Review (GET) and create (POST) a requisition for one order and material, in the panel.

    All rules are in `services/requisitions.py`; this view maps what it returns to a panel
    state. Status codes: 200, 400 (not requestable), 404, 409 (already open).
    """
    material = request.GET.get("material", "")
    if request.method == "GET":
        return _review_panel(request, number, material)

    raw_quantity = request.POST.get("quantity", "")
    try:
        requisition = requisitions.create(request.user, number, material, raw_quantity)
    except requisitions.RequisitionRefused as refused:
        if refused.reason == "invalid_quantity":
            return _review_panel(request, number, material, raw_quantity, error=refused.message)
        if refused.reason == "duplicate":
            return _review_panel(
                request, number, material, raw_quantity, refusal=refused.message, status=409
            )
        return _refusal_panel(request, number, material, refused)
    return _outcome_panel(request, requisition)


@requires(Action.VIEW_BUSINESS)
def requisition_panel(request: HttpRequest, number: str, pk: int) -> HttpResponse:
    """The outcome of one requisition of this order in the panel (every business role)."""
    requisition = get_object_or_404(
        Requisition.objects.select_related("order", "created_by"), pk=pk, order__number=number
    )
    return _outcome_panel(request, requisition)


@requires(Action.VIEW_BUSINESS)
def requisition_panel_empty(request: HttpRequest, number: str) -> HttpResponse:
    """The Empty state: Cancel and Close return here, with no row selected."""
    return _render_panel(request, number, "empty")


@requires(Action.CREATE_REQUISITION)
def requisition_preview(request: HttpRequest, number: str) -> HttpResponse:
    """The "Sent to SAP" value for the quantity being typed: always 200, a dash if not valid.

    Only for HTMX. A plain GET shows the Review state instead.
    """
    material = request.GET.get("material", "")
    if not _is_htmx(request):
        return _review_panel(request, number, material)
    sent = order_panel.preview_sent(number, material, request.GET.get("quantity", ""))
    response = render(request, f"{PANEL_DIR}/sent_to_sap.html", {"sent": sent})
    patch_vary_headers(response, ["HX-Request"])
    return response


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

    template = "cockpit/orders/results.html" if _is_htmx(request) else "cockpit/orders/page.html"
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
    """One order with its components, stock and statuses (ui-spec 4.2; issues #26, #28).

    The side panel starts Empty. The page context is shared with the panel views, which show
    the same page for a request without HTMX (#28).
    """
    context = _order_page_context(request, number)
    context["panel_template"] = f"{PANEL_DIR}/empty.html"
    return render(request, "cockpit/orders/detail.html", context)


def _rows_context(request: HttpRequest, number: str, selected_material: str = "") -> dict:
    """The order and its component rows with their Requisition cells (`selected_material`'s
    rows highlighted). Raises NotFound for an unknown order."""
    detail = plant_status.order_detail(number, timezone.localdate())
    if detail is None:
        raise NotFound(f"Order {number} not found")
    can_create = can(request.user, Action.CREATE_REQUISITION)
    return {
        "order": detail,
        "can_create": can_create,
        "table_rows": order_panel.table_rows(detail, can_create, selected_material),
    }


def _order_page_context(request: HttpRequest, number: str, selected_material: str = "") -> dict:
    """Everything the order page needs: the header, the sync state and the component rows.

    The order is looked up before the sync, because the plant to sync comes from the order; an
    unknown number never calls SAP. Orders are never deleted, so it still exists after the sync.
    """
    order = ProductionOrder.objects.filter(number=number).only("plant").first()
    if order is None:
        raise NotFound(f"Order {number} not found")
    sync = ensure_fresh(order.plant)
    context = _rows_context(request, number, selected_material)
    detail = context["order"]
    context.update(
        sync=sync,
        refresh_url=reverse("cockpit:refresh_plant", args=[detail.plant]),
        breadcrumb_items=[
            ("Orders", f"{reverse('cockpit:order_list')}?{urlencode({'plant': detail.plant})}"),
            (detail.number, None),
        ],
        subline=_order_subline(detail),
        pill_key=PILL_KEYS.get(detail.status) if detail.status else None,
    )
    if sync.failed and sync.synced_at is not None:
        context["banner_text"] = (
            f"SAP could not be reached. Showing data as of {format_datetime(sync.synced_at)}."
        )
    return context


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
