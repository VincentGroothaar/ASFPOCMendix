"""Tests for the order detail page (issue #26): `plant_status.order_detail`, the view and the 404.

The snapshot is written straight into the test database with a fresh `synced_at`, so
`ensure_fresh` never calls SAP. Where a sync would run, the SAP settings are empty: that is a
failed sync that stores nothing and calls nobody (#69).
"""

import re
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest import mock

import pytest
import time_machine
from django.template import Context, Template
from pytest_django.asserts import assertContains, assertNotContains

from cockpit.models import BufferChange, Component, PlantSnapshot, ProductionOrder, Stock
from cockpit.services import plant_status
from cockpit.services.shortage import Status

NOW = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)  # 10:00 in Amsterdam
TODAY = date(2026, 11, 3)

pytestmark = pytest.mark.django_db

SHORT_TIP = (
    "Short: available stock is below the open requirement, after earlier orders take their share."
)


@pytest.fixture(autouse=True)
def clock():
    with time_machine.travel(NOW, tick=False) as traveller:
        yield traveller


@pytest.fixture(autouse=True)
def no_sap(settings):
    """No SAP connection, so a sync never leaves the test."""
    settings.SAP_BASE_URL = ""
    settings.COCKPIT_PLANTS = ["AUC1", "USC1"]


def synced(plant: str = "AUC1", at: datetime = NOW, error: str = "") -> PlantSnapshot:
    """A stored snapshot, synced at `at`; with `error`, the latest attempt failed afterwards."""
    return PlantSnapshot.objects.create(
        plant=plant,
        synced_at=at,
        last_sync_error=error,
        last_sync_error_at=NOW if error else None,
    )


def order(
    number: str = "1000123",
    start: date = date(2026, 11, 5),
    lines: list[tuple] = (),
    active: bool = True,
    plant: str = "AUC1",
) -> ProductionOrder:
    """An order with component lines (item, material, required, unit[, withdrawn])."""
    stored = ProductionOrder.objects.create(
        number=number,
        plant=plant,
        material="FG-210",
        description="Pump assembly",
        quantity=Decimal("20"),
        unit="PC",
        start_date=start,
        is_active=active,
        synced_at=NOW,
    )
    for item, material, required, unit, *rest in lines:
        Component.objects.create(
            order=stored,
            item=item,
            material=material,
            description=f"{material} part",
            required_quantity=Decimal(required),
            withdrawn_quantity=Decimal(rest[0] if rest else "0"),
            unit=unit,
        )
    return stored


def stock(material: str, quantity: str, unit: str = "PC", plant: str = "AUC1") -> None:
    Stock.objects.create(
        plant=plant, material=material, quantity=Decimal(quantity), unit=unit, synced_at=NOW
    )


def mixed_order() -> ProductionOrder:
    """One order with a line of each status, in item order 10, 20, 30, 40, 50, 60.

    Item 9 sorts before item 10 when compared as an integer (#20).
    """
    stored = order(
        lines=[
            ("10", "RM-SHORT", "100", "PC"),
            ("20", "RM-LOW", "100", "PC"),
            ("30", "RM-COVER", "2", "KG"),
            ("40", "RM-MIX", "20", "M"),
            ("50", "RM-ISSUED", "5", "PC", "5"),
            ("9", "RM-FIRST", "1", "PC"),
        ]
    )
    stock("RM-SHORT", "70")
    stock("RM-LOW", "104")
    stock("RM-COVER", "3200", unit="G")
    stock("RM-MIX", "35", unit="PC")
    stock("RM-FIRST", "10")
    return stored


# --- Service: plant_status.order_detail ---------------------------------------------------------


def test_unknown_order_gives_none() -> None:
    assert plant_status.order_detail("999", TODAY) is None


def test_rows_carry_status_quantities_and_item_order() -> None:
    mixed_order()

    detail = plant_status.order_detail("1000123", TODAY)

    assert [row.item for row in detail.rows] == ["9", "10", "20", "30", "40", "50"]
    rows = {row.material: row for row in detail.rows}
    assert rows["RM-SHORT"].status == Status.SHORT
    assert rows["RM-SHORT"].available == Decimal("70")
    assert rows["RM-SHORT"].shortage == Decimal("30")
    assert rows["RM-LOW"].status == Status.LOW_COVER
    assert rows["RM-COVER"].status == Status.COVERED
    assert rows["RM-COVER"].available == Decimal("3.2")
    assert rows["RM-COVER"].available_in_stock_unit == Decimal("3200")
    assert rows["RM-COVER"].converted
    assert not rows["RM-SHORT"].converted
    assert rows["RM-SHORT"].description == "RM-SHORT part"
    assert detail.status == Status.SHORT
    assert detail.unit_mismatch
    assert not detail.overdue
    assert detail.buffer_percent == Decimal("10")


def test_mismatch_and_issued_rows_have_no_available_or_shortage() -> None:
    """D-1 (service part)."""
    mixed_order()

    rows = {row.material: row for row in plant_status.order_detail("1000123", TODAY).rows}

    assert rows["RM-MIX"].status == Status.UNIT_MISMATCH
    assert rows["RM-MIX"].stock_unit == "PC"
    assert (rows["RM-MIX"].available, rows["RM-MIX"].shortage) == (None, None)
    assert not rows["RM-MIX"].converted
    assert rows["RM-ISSUED"].status == Status.ISSUED
    assert rows["RM-ISSUED"].open_requirement == Decimal("0")
    assert (rows["RM-ISSUED"].available, rows["RM-ISSUED"].shortage) == (None, None)


def test_inactive_order_shows_its_lines_without_statuses() -> None:
    """Decision 2: the last synced lines with the open requirement only."""
    order(lines=[("10", "RM-1", "10", "PC", "4"), ("20", "RM-2", "5", "PC", "9")], active=False)
    stock("RM-1", "100")

    detail = plant_status.order_detail("1000123", TODAY)

    assert not detail.is_active
    assert detail.status is None
    assert not detail.overdue
    assert [row.open_requirement for row in detail.rows] == [Decimal("6"), Decimal("0")]
    assert all(row.status is None and row.available is None for row in detail.rows)


def test_statuses_match_the_whole_plant_calculation() -> None:
    """D-8 / INV-6: an earlier order takes its share first, a later one changes nothing."""
    order("1000001", date(2026, 11, 4), [("10", "RM-1", "60", "PC")])
    order("1000002", date(2026, 11, 5), [("10", "RM-1", "60", "PC")])
    stock("RM-1", "100")
    before = plant_status.order_detail("1000002", TODAY)
    order("1000003", date(2026, 12, 30), [("10", "RM-1", "500", "PC")])

    after = plant_status.order_detail("1000002", TODAY)

    assert before == after
    assert after.rows[0].available == Decimal("40")
    assert (
        after.rows[0].status
        == plant_status.plant_result("AUC1", TODAY).component("1000002", "10").status
    )


def test_overdue_and_buffer_come_from_the_calculation() -> None:
    order(start=date(2026, 11, 1), lines=[("10", "RM-1", "100", "PC")])
    stock("RM-1", "112.4")
    BufferChange.objects.create(value=Decimal("12.5"), changed_by=_user())

    detail = plant_status.order_detail("1000123", TODAY)

    assert detail.overdue
    assert detail.buffer_percent == Decimal("12.50")
    assert detail.rows[0].status == Status.LOW_COVER


def _user():
    from django.contrib.auth.models import User

    return User.objects.get_or_create(username="manager")[0]


# --- Template tags ------------------------------------------------------------------------------


def render(source: str, **context) -> str:
    return Template("{% load ui %}" + source).render(Context(context))


@pytest.mark.parametrize(
    ("buffer", "low", "covered"),
    [
        (
            Decimal("10.00"),
            "Low cover: covered, but less than 10% to spare (available below 110% of required). "
            "Nothing is reserved.",
            "Covered: at least 10% to spare.",
        ),
        (
            Decimal("12.50"),
            "Low cover: covered, but less than 12.5% to spare (available below 112.5% of "
            "required). Nothing is reserved.",
            "Covered: at least 12.5% to spare.",
        ),
        (
            Decimal("0"),
            "Low cover: covered, but less than 0% to spare (available below 100% of required). "
            "Nothing is reserved.",
            "Covered: at least 0% to spare.",
        ),
    ],
)
def test_component_tooltips_show_the_buffer_word_for_word(buffer, low, covered) -> None:
    """ui-spec 5.2, D-2: never `1E+1%`."""
    tag = "{% component_status_tip status buffer 'PC' 'PC' %}"

    assert render(tag, status="low_cover", buffer=buffer) == low
    assert render(tag, status="covered", buffer=buffer) == covered
    assert render(tag, status="short", buffer=buffer) == SHORT_TIP


def test_mismatch_and_issued_tooltips_word_for_word() -> None:
    tag = "{% component_status_tip status buffer 'M' 'PC' %}"
    buffer = Decimal("10")

    assert render(tag, status="unit_mismatch", buffer=buffer) == (
        "Unit mismatch: order unit M and stock unit PC can&#x27;t be converted, so this "
        "component isn&#x27;t checked."
    )
    assert render(tag, status="issued", buffer=buffer) == (
        "Issued: no open requirement left, so it isn&#x27;t checked."
    )


def test_page_header_without_new_arguments_renders_as_before() -> None:
    """D-3: existing callers do not change."""
    html = render('{% page_header "Requisitions" "sent" "REQ-1" %}')

    assert "mismatch-icon" not in html
    assert "Overdue" not in html


def test_page_header_with_overdue_and_mismatch() -> None:
    html = render(
        '{% page_header "Order 1" "short" "FG · Plant AUC1" overdue=True unit_mismatch=True %}'
    )

    assert "Overdue</span>" in html
    assert html.index("FG · Plant AUC1") < html.index("Overdue")
    assert 'tabindex="0"' in html
    assert html.count("Unit mismatch: a component isn&#x27;t checked") == 2  # label + tooltip


def test_value_tip_keeps_the_value_text_separate() -> None:
    html = render('{% value_tip "1.5 KG" "1,500 G (= 1.5 KG)" %}')

    assert '<span class="value-tip" tabindex="0"' in html
    assert ">1.5 KG</span>" in html
    assert 'role="tooltip">1,500 G (= 1.5 KG)</span>' in html


# --- View ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("groups", [("Admin",), (), ("Viewer", "Planner")])
def test_admin_and_users_without_a_role_are_refused(client_as, groups) -> None:
    """D-7."""
    synced()
    mixed_order()

    assert client_as(*groups).get("/orders/1000123/").status_code == 403


def test_anonymous_is_sent_to_login(client) -> None:
    response = client.get("/orders/1000123/")

    assert response.status_code == 302
    assert response["Location"].startswith("/accounts/login/")


@pytest.mark.parametrize("role", ["Viewer", "Planner", "Manager"])
def test_business_roles_see_the_page(client_as, role) -> None:
    """D-7 (as changed by #28, I-3): the same page for every role; the Requisition column has a
    Request button on short and low cover lines for Planner and Manager, and a dash otherwise
    (and for the Viewer, with a note); the side panel starts Empty."""
    synced()
    mixed_order()

    response = client_as(role).get("/orders/1000123/")

    assertContains(response, "<h1>Order 1000123</h1>", html=True)
    cells = {
        row.split('<span class="cell-main">')[1].split("</span>")[0]: _requisition_cell(row)
        for row in _rows(response.content.decode())
    }
    requestable = {"RM-SHORT", "RM-LOW"} if role != "Viewer" else set()
    assert {m for m, cell in cells.items() if cell == "Request"} == requestable
    assert all(cell in ("Request", "–") for cell in cells.values())
    note = "You can view requisitions but not create them."
    (assertContains if role == "Viewer" else assertNotContains)(response, note)
    assertContains(response, "<h2>Requisition</h2>", html=True)
    assertContains(
        response,
        "Choose Request on a short or low-cover component, or open an existing requisition.",
    )


def test_header_breadcrumb_subline_and_refresh(client_as) -> None:
    """D-3, D-6: header per ui-spec 4.2; breadcrumb keeps the plant; Refresh posts to #25."""
    synced()
    mixed_order()

    response = client_as("Viewer").get("/orders/1000123/")

    assertContains(response, '<a href="/orders/?plant=AUC1">Orders</a>', html=True)
    assertContains(
        response, "FG-210 · Pump assembly · Plant AUC1 · Start 05 Nov 2026 · 20 PC · Released"
    )
    assertContains(response, 'hx-post="/plants/AUC1/refresh/"')
    assertContains(response, "Data as of 03 Nov 10:00")
    assertContains(response, "Unit mismatch: a component isn&#x27;t checked")
    assertNotContains(response, "Overdue")


def test_overdue_pill_and_no_pill_without_status(client_as) -> None:
    """D-3: Overdue at the end of the sub-line; no order pill when no line counts."""
    synced()
    order(start=date(2026, 11, 1), lines=[("10", "RM-ISSUED", "5", "PC", "5")])

    html = client_as("Viewer").get("/orders/1000123/").content.decode()

    title = html[
        html.index('<div class="page-title-line">') : html.index(
            "</div>", html.index('<div class="page-title-line">')
        )
    ]
    assert "pill" not in title
    assert html.index("Released") < html.index("Overdue</span>")


def test_rows_show_quantities_tooltips_and_dashes(client_as) -> None:
    """D-1, AC-13 (server side): converted stock has its original in a tooltip."""
    synced()
    mixed_order()

    html = client_as("Viewer").get("/orders/1000123/").content.decode()

    assert ">3.2 KG</span>" in html
    assert "3,200 G (= 3.2 KG)" in html
    assert "What does Unit mismatch mean?" in html
    assert "What does Issued mean?" in html
    assert SHORT_TIP in html
    mismatch_row = _row(html, "RM-MIX")
    assert mismatch_row.count("–") >= 3  # available, shortage, requisition
    assert "20 M" in mismatch_row
    issued_row = _row(html, "RM-ISSUED")
    assert "0 PC" in issued_row


def _rows(html: str) -> list[str]:
    body = html[html.index('<tbody id="components-body">') : html.index("</tbody>")]
    return body.split("<tr ")[1:]


def _requisition_cell(row: str) -> str:
    last_cell = row.rsplit("<td>", 1)[1]
    return re.sub(r"<[^>]+>", "", last_cell).strip()


def _row(html: str, material: str) -> str:
    start = html.index(f'<span class="cell-main">{material}</span>')
    return html[start : html.index("</tr>", start)]


def test_buffer_change_shows_in_the_tooltips(client_as) -> None:
    """D-2."""
    synced()
    mixed_order()
    BufferChange.objects.create(value=Decimal("12.5"), changed_by=_user())

    response = client_as("Viewer").get("/orders/1000123/")

    assertContains(response, "less than 12.5% to spare (available below 112.5% of required)")
    assertContains(response, "Covered: at least 12.5% to spare.")


def test_inactive_order_shows_the_note(client_as) -> None:
    """D-5."""
    synced()
    order(lines=[("10", "RM-1", "10", "PC", "4")], active=False)

    response = client_as("Viewer").get("/orders/1000123/")

    assert response.status_code == 200
    assertContains(response, "This order is no longer released in SAP, so it isn't checked.")
    assertContains(response, "6 PC")
    assertNotContains(response, "Released")
    assertNotContains(response, "What does")


def test_unknown_order_is_a_404_without_sap(client_as) -> None:
    """D-4."""
    with mock.patch("cockpit.views.ensure_fresh") as ensure_fresh:
        response = client_as("Viewer").get("/orders/999/")

    ensure_fresh.assert_not_called()
    assert response.status_code == 404
    assertContains(response, "<h1>Order 999 not found</h1>", status_code=404, html=True)
    assertContains(response, "Back to orders", status_code=404)


def test_unknown_url_logged_in_shows_page_not_found(client_as) -> None:
    """D-4: never the path or the URL patterns."""
    response = client_as("Viewer").get("/no-such-page/")

    assert response.status_code == 404
    assertContains(response, "<h1>Page not found</h1>", status_code=404, html=True)
    assertNotContains(response, "no-such-page", status_code=404)
    assertNotContains(response, "orders/&lt;str:number&gt;", status_code=404)
    assertNotContains(response, "orders/<str:number>", status_code=404)


def test_unknown_url_logged_out_goes_to_login(client) -> None:
    """D-4 / N-1."""
    response = client.get("/no-such-page/")

    assert response.status_code == 302
    assert response["Location"] == "/accounts/login/?next=/no-such-page/"


def test_unknown_url_logged_out_htmx_gets_hx_redirect(client) -> None:
    response = client.get(
        "/no-such-page/",
        HTTP_HX_REQUEST="true",
        HTTP_HX_CURRENT_URL="http://testserver/orders/",
    )

    assert response["HX-Redirect"] == "/accounts/login/?next=%2Forders%2F"


def test_stale_snapshot_syncs_on_load(client_as, caplog) -> None:
    """D-6: older than 5 minutes → the page load runs a sync (here it fails: no SAP)."""
    synced(at=NOW - timedelta(minutes=6))
    mixed_order()

    with caplog.at_level("INFO", logger="cockpit.sync"):
        client_as("Viewer").get("/orders/1000123/")

    assert "sync plant=AUC1" in caplog.text


def test_fresh_snapshot_does_not_sync(client_as, caplog) -> None:
    synced(at=NOW - timedelta(minutes=4))
    mixed_order()

    with caplog.at_level("INFO", logger="cockpit.sync"):
        client_as("Viewer").get("/orders/1000123/")

    assert "sync plant=" not in caplog.text


def test_failed_sync_shows_the_banner(client_as) -> None:
    """D-6: SAP down after an earlier success → banner with the last successful time."""
    synced(at=NOW - timedelta(minutes=6), error="SAP could not be reached")
    mixed_order()

    response = client_as("Viewer").get("/orders/1000123/")

    assertContains(response, "SAP could not be reached. Showing data as of 03 Nov 09:54.")
    assertContains(response, "Try again")
