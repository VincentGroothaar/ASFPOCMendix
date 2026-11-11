"""The shared UI components (ui-spec 3, AC-47, AC-48, AC-54)."""

import re
from datetime import UTC, datetime

import pytest
from django.core.paginator import Paginator
from django.http import QueryDict
from django.template import Context, Template
from pytest_django.asserts import assertHTMLEqual, assertInHTML


def render(source: str, **context) -> str:
    return Template("{% load ui %}" + source).render(Context(context))


@pytest.mark.parametrize(
    ("status", "label", "tone", "dot"),
    [
        ("short", "Short", "short", True),
        ("low", "Low cover", "low", True),
        ("covered", "Covered", "covered", True),
        ("mismatch", "Unit mismatch", "neutral", False),
        ("issued", "Issued", "neutral", False),
        ("overdue", "Overdue", "neutral", False),
        ("awaiting_approval", "Awaiting approval", "low", True),
        ("sent", "PR sent", "info", True),
        ("failed", "PR failed", "short", True),
        ("rejected", "Rejected", "neutral", True),
    ],
)
def test_status_pill(status, label, tone, dot) -> None:
    html = render("{% status_pill status %}", status=status)

    dot_html = '<span class="pill-dot" aria-hidden="true"></span>' if dot else ""
    assertHTMLEqual(html, f'<span class="pill pill-{tone}">{dot_html}{label}</span>')


@pytest.mark.parametrize("tag", ["status_pill", "requisition_label"])
def test_an_unknown_status_is_refused(tag) -> None:
    with pytest.raises(ValueError, match="Unknown"):
        render(f'{{% {tag} "red" %}}')


@pytest.mark.parametrize(
    ("status", "label", "tone"),
    [
        ("sent", "PR sent", "info"),
        ("awaiting_approval", "Awaiting approval", "low"),
        ("failed", "PR failed", "short"),
        ("rejected", "Rejected", "neutral"),
    ],
)
def test_requisition_label(status, label, tone) -> None:
    plain = render("{% requisition_label status %}", status=status)
    as_button = render('{% requisition_label status "/panel/1/" %}', status=status)

    assertHTMLEqual(plain, f'<span class="req-label req-label-{tone}">{label}</span>')
    assertHTMLEqual(
        as_button,
        f'<button type="button" class="req-label req-label-{tone}" hx-get="/panel/1/" '
        f'hx-target="#side-panel">{label}</button>',
    )


def test_no_requisition_is_a_dash_and_never_a_button() -> None:
    html = render('{% requisition_label "none" "/panel/1/" %}')

    assertHTMLEqual(html, '<span class="muted">–</span>')


def test_info_tooltip_links_the_button_to_its_text() -> None:
    html = render('{% info_tooltip "Short" "Short: available stock is below." %}')

    button_id = re.search(r'aria-describedby="([^"]+)"', html).group(1)
    assert 'aria-label="What does Short mean?"' in html
    assert f'<span class="tooltip" id="{button_id}" role="tooltip">' in html
    assert "Short: available stock is below.</span>" in html


def test_each_tooltip_gets_its_own_id() -> None:
    html = render('{% info_tooltip "A" "a" %}{% info_tooltip "B" "b" %}')

    ids = re.findall(r'id="(tip-\d+)"', html)
    assert len(ids) == 2 and ids[0] != ids[1]


def test_kpi_tile_is_a_toggle_button_with_the_info_next_to_it() -> None:
    html = render('{% kpi_tile "Short" 4 "short" True "status" "" "filters" "Short tooltip" %}')

    button = re.search(r"<button type=\"submit\".*?</button>", html, re.S).group(0)
    assert 'form="filters"' in button
    assert 'name="status" value=""' in button
    assert 'aria-pressed="true"' in button
    assert "What does Short mean?" not in button  # the ⓘ is a sibling, not inside the tile
    assert html.index(button) < html.index("What does Short mean?")


def test_all_orders_tile_has_no_info() -> None:
    html = render('{% kpi_tile "All orders" 8 None False "status" "" %}')

    assert 'aria-pressed="false"' in html
    assert "What does" not in html
    assert "form=" not in html


def test_kpi_tile_refuses_an_unknown_status() -> None:
    with pytest.raises(ValueError):
        render('{% kpi_tile "Red" 1 "red" False "status" "red" %}')


def test_summary_strip_with_tones() -> None:
    items = [
        ("Shortage", "6 PC", "short"),
        ("Requested", "6 PC"),
        ("Sent to SAP", "6 PC", "primary"),
    ]
    html = render("{% summary_strip items %}", items=items)

    assertInHTML('<dd class="tone-short">6 PC</dd>', html)
    assertInHTML("<dt>Requested</dt>", html)
    assertInHTML('<dd class="tone-primary">6 PC</dd>', html)


def test_page_header_with_pill_subline_data_as_of_and_refresh() -> None:
    html = render(
        '{% page_header "Order 1000123" "short" "FG-210 · Pump assembly" synced refresh %}',
        synced=datetime(2026, 11, 2, 9, 2, tzinfo=UTC),
        refresh="/plants/AUC1/refresh/",
    )

    assertInHTML("<h1>Order 1000123</h1>", html)
    assert '<span class="pill pill-short">' in html
    assertInHTML('<p class="page-subline">FG-210 · Pump assembly</p>', html)
    assertInHTML('<span class="muted">Data as of 02 Nov 10:02</span>', html)
    refresh = re.search(r"<button[^>]*>", html).group(0)
    assert 'hx-post="/plants/AUC1/refresh/"' in refresh
    assert 'hx-swap="none"' in refresh
    assert 'hx-disabled-elt="this"' in refresh


def test_page_header_without_data_shows_no_refresh() -> None:
    html = render('{% page_header "Requisitions" %}')

    assert "Refresh" not in html
    assert "Data as of" not in html


def test_breadcrumb_links_every_part_but_the_last() -> None:
    html = render("{% breadcrumb items %}", items=[("Orders", "/orders/"), ("1000123", None)])

    assertInHTML('<a href="/orders/">Orders</a>', html)
    assertInHTML('<span aria-current="page">1000123</span>', html)


def test_pagination_keeps_the_filters_and_disables_the_ends() -> None:
    paginator = Paginator(list(range(120)), 50)
    query = QueryDict("plant=AUC1&from=2026-11-02&page=1")

    first = render('{% pagination page "orders" query %}', page=paginator.page(1), query=query)
    middle = render('{% pagination page "orders" query %}', page=paginator.page(2), query=query)

    assert "Showing 50 of 120 orders" in first
    assertInHTML(
        '<button type="button" class="btn btn-secondary" disabled>Previous</button>', first
    )
    assert 'href="?plant=AUC1&amp;from=2026-11-02&amp;page=2"' in first
    assert 'href="?plant=AUC1&amp;from=2026-11-02&amp;page=1"' in middle
    assert 'href="?plant=AUC1&amp;from=2026-11-02&amp;page=3"' in middle


def test_banner_with_a_post_action() -> None:
    html = render('{% banner "SAP could not be reached." "Try again" "/retry/" "post" %}')

    assert 'hx-post="/retry/"' in html
    assert ">Try again</button>" in html


def test_banner_with_a_link_action() -> None:
    html = render('{% banner "3 awaiting your approval" "Show" "?status=awaiting" %}')

    assertInHTML('<a class="btn btn-ghost" href="?status=awaiting">Show</a>', html)


def test_error_note() -> None:
    assertHTMLEqual(
        render('{% error_note "SAP said no." %}'),
        '<p class="error-note" role="alert">SAP said no.</p>',
    )


def test_timeline_states() -> None:
    steps = [
        ("done", "Requested", "planner.a · 02 Nov 10:11"),
        ("waiting", "Manager approval", ""),
        ("failed", "Sent to SAP", ""),
        ("not_reached", "Sent to SAP", ""),
    ]
    html = render("{% timeline steps %}", steps=steps)

    for state in ("done", "waiting", "failed", "not_reached"):
        assert f"step-{state}" in html
    with pytest.raises(ValueError):
        render("{% timeline steps %}", steps=[("lost", "x", "")])


def test_icons_are_hidden_from_screen_readers() -> None:
    html = render('{% icon "refresh" 16 %}')

    assert 'aria-hidden="true"' in html and 'width="16"' in html
    with pytest.raises(ValueError):
        render('{% icon "rocket" %}')


def test_format_filters() -> None:
    from decimal import Decimal

    html = render(
        "{{ q|quantity:'PC' }} | {{ s|quantity_sent:'KG' }} | {{ m|money:'EUR' }}",
        q=Decimal("20.000"),
        s=Decimal("8"),
        m=Decimal("1250"),
    )

    assert html == "20 PC | 8.000 KG | 1,250.00 EUR"
