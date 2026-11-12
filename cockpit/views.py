"""Views handle the HTTP request and render a template.

Keep business logic out of here: put it in `cockpit/services/` and call it.
Every view needs a login (middleware) and declares its role check with `@requires(...)`.
"""

from decimal import Decimal
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth.views import LogoutView
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from cockpit.access import requires
from cockpit.models import Requisition
from cockpit.services import formats, requisition_views, requisitions
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
