"""What the requisition list and the requisition detail page show (REQ-5, #29).

Plain functions that read the `Requisition` model and prepare it for a page: filtering and
paging the list, the Progress timeline, the Retry rule and the Technical details. The views
only call these and render a template. Nothing here changes data.
In Mendix terms: the microflows behind two overview and detail pages.
"""

import json
from dataclasses import dataclass
from urllib.parse import urlencode

from django.contrib.auth.models import AbstractBaseUser, AnonymousUser
from django.core.paginator import Page, Paginator
from django.urls import reverse

from cockpit.models import Component, Requisition
from cockpit.services.formats import format_datetime
from cockpit.services.roles import Action, can

PAGE_SIZE = 50  # D-17

Status = Requisition.Status

# The values of the Status select on the list (ui-spec 4.4), as used in `?status=`.
STATUS_FILTERS: dict[str, str] = {status.value: status.label for status in Status}

NO_PR_YET = "No PR number yet"
NO_PR = "No PR number"
NO_REQUEST_SENT = "Nothing was sent."
NO_RESPONSE = "No response received."


@dataclass(frozen=True)
class RequisitionList:
    """One page of the list plus the filters that produced it."""

    page: Page
    status: str  # "" means All
    only_mine: bool

    @property
    def status_label(self) -> str:
        """The name of the selected status, for the toolbar title."""
        return STATUS_FILTERS.get(self.status, "")

    @property
    def filtered(self) -> bool:
        """True when a filter is on, so the toolbar shows Clear."""
        return bool(self.status) or self.only_mine


def list_requisitions(
    user: AbstractBaseUser | AnonymousUser, status: str, only_mine: bool, page_number: str
) -> RequisitionList:
    """Return one page of requisition attempts, newest first, for the list screen.

    An unknown `status` counts as All. A page number that is not a number or is below 1 shows
    page 1, and one past the end shows the last page. Each requisition on the page gets a
    `description` attribute (the material's description from its order's components) and a
    `pr_text` attribute (see `pr_text`).
    """
    if status not in STATUS_FILTERS:
        status = ""
    queryset = Requisition.objects.select_related("order", "created_by").order_by(
        "-created_at", "-id"
    )
    if status:
        queryset = queryset.filter(status=status)
    if only_mine:
        queryset = queryset.filter(created_by=user)

    page = Paginator(queryset, PAGE_SIZE).get_page(_page_number(page_number))
    _add_descriptions(list(page.object_list))
    return RequisitionList(page=page, status=status, only_mine=only_mine)


def _page_number(raw: str) -> int:
    """The requested page as a number: anything that is not a number, or below 1, is page 1."""
    try:
        return max(int(raw), 1)
    except (TypeError, ValueError):
        return 1


def _add_descriptions(requisitions: list[Requisition]) -> None:
    """Set `description` on each requisition, using one query for the whole page."""
    if not requisitions:
        return
    components = Component.objects.filter(
        order_id__in={r.order_id for r in requisitions},
        material__in={r.material for r in requisitions},
    ).exclude(description="")
    found = {(c.order_id, c.material): c.description for c in components}
    for requisition in requisitions:
        requisition.description = found.get((requisition.order_id, requisition.material), "")
        requisition.pr_text = pr_text(requisition)


def describe(requisition: Requisition) -> Requisition:
    """Set `description` on a single requisition (for the detail page) and return it."""
    _add_descriptions([requisition])
    return requisition


def pr_text(requisition: Requisition) -> str:
    """The PR number, or why there is none: `No PR number yet`, or `No PR number` when rejected."""
    if requisition.pr_number:
        return f"PR {requisition.pr_number}"
    return NO_PR if requisition.status == Status.REJECTED else NO_PR_YET


def _who_when(user: AbstractBaseUser | None, when) -> str:
    """The sub-line of a timeline step: `pat · 02 Nov 10:11`."""
    name = user.get_username() if user else ""
    stamp = format_datetime(when) if when else ""
    return " · ".join(part for part in (name, stamp) if part)


def requisition_timeline(requisition: Requisition) -> list[tuple[str, str, str]]:
    """The Progress steps for one requisition (ui-spec 4.5), as (state, title, sub-line).

    Approval steps appear only when a Manager decided on it (`decided_by` is set).
    """
    requested = ("done", "Requested", _who_when(requisition.created_by, requisition.created_at))
    approved = ("done", "Approved", _who_when(requisition.decided_by, requisition.decided_at))
    sent_at = requisition.sent_at or requisition.created_at
    status = requisition.status

    if status == Status.AWAITING_APPROVAL:
        return [
            requested,
            ("waiting", "Manager approval", "Waiting for a manager"),
            ("not_reached", "Sent to SAP", ""),
        ]
    if status == Status.REJECTED:
        rejected = ("failed", "Rejected", _who_when(requisition.decided_by, requisition.decided_at))
        return [requested, rejected]

    steps = [requested]
    if requisition.decided_by_id:
        steps.append(approved)
    if status == Status.SENT:
        sub = " · ".join(part for part in (requisition.pr_number, format_datetime(sent_at)) if part)
        steps.append(("done", "Sent to SAP", sub))
    else:
        steps.append(("failed", "Sent to SAP", format_datetime(sent_at)))
    return steps


def shows_technical_details(requisition: Requisition) -> bool:
    """Technical details appear only for a sent or a failed requisition (D-33)."""
    return requisition.status in (Status.SENT, Status.FAILED)


def technical_details(requisition: Requisition) -> tuple[str, str]:
    """The stored request and response as text, with a fallback line for an empty part."""
    return (
        _pretty(requisition.payload, NO_REQUEST_SENT),
        _pretty(requisition.response, NO_RESPONSE),
    )


def _pretty(value, fallback: str) -> str:
    """JSON text with indentation, or `fallback` when the value is None or empty."""
    if value in (None, {}, []):
        return fallback
    return json.dumps(value, indent=2, ensure_ascii=False)


def retry_url(user: AbstractBaseUser | AnonymousUser, requisition: Requisition) -> str | None:
    """The confirm-step URL for Retry, or None when Retry must not show.

    Retry shows only to a user who may create requisitions, on a failed requisition, and only
    while it is the latest attempt: a row with a higher id for the same order and material
    (a later retry, or a new request) hides it.
    """
    if requisition.status != Status.FAILED or not can(user, Action.CREATE_REQUISITION):
        return None
    has_later_attempt = Requisition.objects.filter(
        order_id=requisition.order_id, material=requisition.material, id__gt=requisition.id
    ).exists()
    if has_later_attempt:
        return None
    query = urlencode({"material": requisition.material})
    return f"{reverse('cockpit:requisition_create', args=[requisition.order.number])}?{query}"
