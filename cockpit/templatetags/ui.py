"""Shared UI components (ui-spec section 3) as template tags.

Use them in a template after `{% load ui %}`, for example `{% status_pill "short" %}`.
Each tag checks its input and renders a small template in `templates/components/`.
In Mendix terms: these are the building blocks (snippets) every page reuses.

Statuses and labels use the values the rest of the app uses: shortage statuses from the
status calculation, and `Requisition.Status` values from `cockpit/models.py`.
"""

import itertools
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from django import template
from django.http import QueryDict

from cockpit.services import formats
from cockpit.services.shortage import Status

register = template.Library()


@dataclass(frozen=True)
class PillStyle:
    """How one status looks: its text, its colour pair from tokens.css, and whether it has a dot."""

    label: str
    tone: str
    dot: bool


# ui-spec 3.1 (component and order statuses) and 4.4/4.5 (requisition statuses as filled pills).
STATUS_PILLS: dict[str, PillStyle] = {
    "short": PillStyle("Short", "short", dot=True),
    "low": PillStyle("Low cover", "low", dot=True),
    "covered": PillStyle("Covered", "covered", dot=True),
    "mismatch": PillStyle("Unit mismatch", "neutral", dot=False),
    "issued": PillStyle("Issued", "neutral", dot=False),
    "overdue": PillStyle("Overdue", "neutral", dot=False),
    "awaiting_approval": PillStyle("Awaiting approval", "low", dot=True),
    "sent": PillStyle("PR sent", "info", dot=True),
    "failed": PillStyle("PR failed", "short", dot=True),
    "rejected": PillStyle("Rejected", "neutral", dot=True),
}

# The pill of each component status from the calculation (#20).
COMPONENT_PILL_KEYS: dict[Status, str] = {
    Status.SHORT: "short",
    Status.LOW_COVER: "low",
    Status.COVERED: "covered",
    Status.UNIT_MISMATCH: "mismatch",
    Status.ISSUED: "issued",
}

# Hover text of the unit mismatch warning next to an order status (D-31).
UNIT_MISMATCH_WARNING = "Unit mismatch: a component isn't checked"

# ui-spec 3.2: outlined labels. "none" means no requisition and shows a dash.
REQUISITION_LABELS: dict[str, PillStyle] = {
    "sent": PillStyle("PR sent", "info", dot=False),
    "awaiting_approval": PillStyle("Awaiting approval", "low", dot=False),
    "failed": PillStyle("PR failed", "short", dot=False),
    "rejected": PillStyle("Rejected", "neutral", dot=False),
}
NO_REQUISITION = "none"

# ui-spec 3.4: the tiles that filter the order list. None is the "All orders" tile.
KPI_STATUSES = frozenset({"short", "low", "covered"})

# ui-spec 3.5 / reference: a summary value can be coloured.
SUMMARY_TONES = frozenset({"short", "primary"})

# ui-spec 3.11.
TIMELINE_STATES: dict[str, str] = {
    "done": "check",
    "waiting": "clock",
    "failed": "x",
    "not_reached": "",
}

ICONS = frozenset(
    {
        "alert-triangle",
        "check",
        "chevron-right",
        "clock",
        "cube",
        "file",
        "filter",
        "grid",
        "info",
        "list",
        "log-out",
        "refresh",
        "sliders",
        "x",
    }
)

# Each ⓘ tooltip needs a unique id on the page, to link the button to its text.
_tooltip_ids = itertools.count(1)


def _check(value: object, allowed, what: str) -> None:
    if value not in allowed:
        raise ValueError(f"Unknown {what}: {value!r}. Use one of {sorted(allowed, key=str)}.")


@register.inclusion_tag("components/icon.html")
def icon(name: str, size: int = 18) -> dict:
    """An inline SVG icon, hidden from screen readers (the label next to it says what it is)."""
    _check(name, ICONS, "icon")
    _check(size, {16, 18, 28}, "icon size")
    return {"path": f"icons/{name}.svg", "size": size}


@register.inclusion_tag("components/status_pill.html")
def status_pill(status: str) -> dict:
    """A filled status pill (ui-spec 3.1), e.g. Short, Low cover, PR sent."""
    _check(status, STATUS_PILLS, "status")
    return {"pill": STATUS_PILLS[status]}


@register.inclusion_tag("components/requisition_label.html")
def requisition_label(status: str, panel_url: str | None = None) -> dict:
    """An outlined requisition label (ui-spec 3.2), or a dash for "none".

    With `panel_url` the label is a GET form with a button: with HTMX it loads the requisition
    into the side panel (`#side-panel`) without leaving the page, and without JavaScript the
    form opens the same URL (#28, R2-2). A dash is never a button.
    """
    _check(status, {*REQUISITION_LABELS, NO_REQUISITION}, "requisition status")
    if status == NO_REQUISITION:
        return {"label": None, "panel_url": None}
    return {"label": REQUISITION_LABELS[status], "panel_url": panel_url}


@register.inclusion_tag("components/info_tooltip.html")
def info_tooltip(subject: str, text: str) -> dict:
    """An ⓘ button with a tooltip shown on hover and keyboard focus (ui-spec 3.3)."""
    return {"subject": subject, "text": text, "tip_id": f"tip-{next(_tooltip_ids)}"}


@register.inclusion_tag("components/value_tip.html")
def value_tip(text: str, tip: str) -> dict:
    """A value that shows a tooltip on hover and keyboard focus, e.g. converted stock (#26).

    The value and the tooltip are separate elements, so the value's own text stays exact.
    """
    return {"text": text, "tip": tip, "tip_id": f"tip-{next(_tooltip_ids)}"}


@register.simple_tag
def component_status_tip(status: str, buffer_percent: Decimal, unit: str, stock_unit: str) -> str:
    """The ⓘ text of a component status (ui-spec 5.2), with the current cover buffer."""
    buffer = buffer_percent.quantize(Decimal("0.01"))
    shown = _percent(buffer)
    texts = {
        Status.SHORT: (
            "Short: available stock is below the open requirement, after earlier orders take "
            "their share."
        ),
        Status.LOW_COVER: (
            f"Low cover: covered, but less than {shown} to spare (available below "
            f"{_percent(buffer + 100)} of required). Nothing is reserved."
        ),
        Status.COVERED: f"Covered: at least {shown} to spare.",
        Status.UNIT_MISMATCH: (
            f"Unit mismatch: order unit {unit} and stock unit {stock_unit} can't be converted, "
            "so this component isn't checked."
        ),
        Status.ISSUED: "Issued: no open requirement left, so it isn't checked.",
    }
    return texts[Status(status)]


@register.filter
def component_pill(status: str) -> str:
    """The `status_pill` key of a component status: `low_cover` → `low` (ui-spec 3.1)."""
    return COMPONENT_PILL_KEYS[Status(status)]


@register.filter
def component_label(status: str) -> str:
    """The screen label of a component status, e.g. `Low cover`, for the ⓘ name."""
    return STATUS_PILLS[COMPONENT_PILL_KEYS[Status(status)]].label


def _percent(value: Decimal) -> str:
    """`10.00` → `10%`, `12.50` → `12.5%` (never `1E+1%`)."""
    text = f"{value:f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return f"{text}%"


@register.inclusion_tag("components/kpi_tile.html")
def kpi_tile(
    label: str,
    count: int,
    status: str | None,
    pressed: bool,
    name: str,
    value: str,
    form_id: str | None = None,
    tooltip: str | None = None,
) -> dict:
    """A KPI tile that works as a filter toggle (ui-spec 3.4).

    The tile is a submit button for the form `form_id`. When it is pressed, pass `value=""`
    so a second click clears the filter. The ⓘ sits next to the button, never inside it.
    """
    if status is not None:
        _check(status, KPI_STATUSES, "tile status")
    return {
        "label": label,
        "count": count,
        "status": status,
        "pressed": pressed,
        "name": name,
        "value": value,
        "form_id": form_id,
        "tooltip": tooltip,
    }


@register.inclusion_tag("components/summary_strip.html")
def summary_strip(items: list) -> dict:
    """Read-only numbers in one strip (ui-spec 3.5).

    Each item is (label, value) or (label, value, tone) with tone "short", "primary" or None.
    """
    rows = []
    for item in items:
        label, value, *rest = item
        tone = rest[0] if rest else None
        if tone is not None:
            _check(tone, SUMMARY_TONES, "summary tone")
        rows.append({"label": label, "value": value, "tone": tone})
    return {"items": rows}


@register.inclusion_tag("components/page_header.html")
def page_header(
    title: str,
    pill_status: str | None = None,
    subline: str | None = None,
    data_as_of: datetime | None = None,
    refresh_url: str | None = None,
    data_screen: bool = False,
    overdue: bool = False,
    unit_mismatch: bool = False,
) -> dict:
    """The page title, an optional status pill and sub-line, and on data screens
    `Data as of` plus a Refresh button (ui-spec 2.1).

    Refresh posts to `refresh_url` and swaps nothing; the refresh view answers with
    `HX-Refresh: true`, so the page reloads with its filters (#24, #25).

    With `data_screen=True` the `#page-data` block is always rendered, also when it is empty
    (state D), so an HTMX response can always replace it out-of-band (#25, R2-I2).

    `overdue` adds the Overdue pill at the end of the sub-line; `unit_mismatch` adds the warning
    icon next to the pill, with its text on hover and keyboard focus (D-18, D-31; #26 I-2).
    """
    if pill_status is not None:
        _check(pill_status, STATUS_PILLS, "status")
    return {
        "title": title,
        "pill_status": pill_status,
        "subline": subline,
        "data_as_of": data_as_of,
        "refresh_url": refresh_url,
        "data_screen": data_screen,
        "overdue": overdue,
        "unit_mismatch": unit_mismatch,
        "mismatch_text": UNIT_MISMATCH_WARNING,
        "tip_id": f"tip-{next(_tooltip_ids)}",
    }


@register.inclusion_tag("components/page_data.html")
def page_data(
    data_as_of: datetime | None = None, refresh_url: str | None = None, oob: bool = False
) -> dict:
    """The `#page-data` block of the page header: `Data as of` and Refresh (ui-spec 2.1).

    With `oob=True` it is marked for an HTMX out-of-band swap, so a filter change can update
    it for the plant now shown (#25, R-B1). Refresh shows the `.sync-indicator` while it runs.
    """
    return {"data_as_of": data_as_of, "refresh_url": refresh_url, "oob": oob}


@register.inclusion_tag("components/breadcrumb.html")
def breadcrumb(items: list) -> dict:
    """A breadcrumb such as `Orders / 1000123` (ui-spec 2.1).

    Each item is (label, url). Every part except the last is a link.
    """
    parts = [{"label": label, "url": url} for label, url in items]
    return {"parts": parts}


@register.inclusion_tag("components/pagination.html")
def pagination(page_obj, noun: str, query: QueryDict | None = None) -> dict:
    """`Showing [n] of [total] [noun]` with Previous / Next (ui-spec 3.7).

    `query` is the current GET parameters (e.g. `request.GET`), so the links keep the filters.
    """
    if query is not None and not isinstance(query, QueryDict):
        raise TypeError("Pass the request's GET parameters (a QueryDict), e.g. request.GET")
    params = query.copy() if query is not None else QueryDict(mutable=True)
    params.pop("page", None)

    def link(number: int) -> str:
        page_params = params.copy()
        page_params["page"] = str(number)
        return "?" + page_params.urlencode()

    return {
        "shown": len(page_obj.object_list),
        "total": page_obj.paginator.count,
        "noun": noun,
        "previous_url": link(page_obj.previous_page_number()) if page_obj.has_previous() else None,
        "next_url": link(page_obj.next_page_number()) if page_obj.has_next() else None,
    }


@register.inclusion_tag("components/banner.html")
def banner(
    text: str,
    action_label: str | None = None,
    action_url: str | None = None,
    action_method: str = "get",
    indicator: str | None = None,
) -> dict:
    """A full-width "needs attention" banner with an optional action (ui-spec 3.12).

    With action_method "post" the action is an HTMX POST button (e.g. Try again).
    `indicator` is a CSS selector of the loading indicator to show while it runs (#25).
    """
    _check(action_method, {"get", "post"}, "banner action method")
    return {
        "text": text,
        "action_label": action_label,
        "action_url": action_url,
        "action_method": action_method,
        "indicator": indicator,
    }


@register.inclusion_tag("components/error_note.html")
def error_note(text: str) -> dict:
    """A plain-language error inside a card (ui-spec 3.12)."""
    return {"text": text}


@register.inclusion_tag("components/timeline.html")
def timeline(steps: list) -> dict:
    """A vertical list of steps (ui-spec 3.11).

    Each step is (state, title, subline) with state "done", "waiting", "failed" or "not_reached".
    """
    rows = []
    for state, title, subline in steps:
        _check(state, TIMELINE_STATES, "timeline state")
        rows.append(
            {"state": state, "icon": TIMELINE_STATES[state], "title": title, "sub": subline}
        )
    return {"steps": rows}


# --- Format filters (ui-spec 6), backed by cockpit/services/formats.py ---------------------


@register.filter
def date_long(value: date) -> str:
    """`03 Nov 2026`."""
    return formats.format_date(value)


@register.filter
def date_short(value: date) -> str:
    """`04 Nov`."""
    return formats.format_short_date(value)


@register.filter
def datetime_short(value: datetime) -> str:
    """`02 Nov 10:11`, in the app's time zone."""
    return formats.format_datetime(value)


@register.filter
def quantity(value: Decimal, unit: str) -> str:
    """`20 PC`, `1,500 G`, `1.235 KG`."""
    return formats.format_quantity(value, unit)


@register.filter
def quantity_sent(value: Decimal, unit: str) -> str:
    """Exactly 3 decimals, as sent to SAP: `8.000 KG`."""
    return formats.format_quantity(value, unit, as_sent=True)


@register.filter
def money(value: Decimal, currency: str) -> str:
    """`1,250.00 EUR`."""
    return formats.format_money(value, currency)
