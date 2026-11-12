"""Tests for the requisition side panel on the order detail page (#28, P-1 to P-8).

Every panel URL answers an HTMX request with the panel fragment plus the out-of-band rows, and
any other request with the whole order page (decisions 7 and I-2). The write client is a fake.
"""

# ruff: noqa: F811  (the fixtures are imported, then used as arguments)

import re

import pytest
from django.test import Client
from pytest_django.asserts import assertContains, assertNotContains

from cockpit.models import Requisition
from cockpit.tests.test_plant_status import add_order, add_stock
from cockpit.tests.test_requisitions import START, mixed_order, resyncs, sent_to  # noqa: F401
from sap.requisitions import RequisitionResult

ORDER = "/orders/1000001/"
CREATE = f"{ORDER}requisitions/"
EMPTY = f"{CREATE}panel/empty/"
PREVIEW = f"{CREATE}preview/"
HTMX = {"HTTP_HX_REQUEST": "true"}
OOB_ROWS = '<template><tbody id="components-body" hx-swap-oob="true">'

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def no_sap(settings):
    """No SAP connection, so the full page's sync never leaves the test (and stores nothing)."""
    settings.SAP_BASE_URL = ""


def selected_rows(html: str) -> list[str]:
    """The materials of the highlighted rows."""
    rows = re.findall(r'<tr id="row-\d+" class="is-selected".*?</tr>', html, re.S)
    return [re.search(r'cell-main">([^<]+)<', row).group(1) for row in rows]


def row_of(html: str, material: str) -> str:
    start = html.index(f'<span class="cell-main">{material}</span>')
    return html[start : html.index("</tr>", start)]


# --- Review (P-1, P-6) ---------------------------------------------------------------------------


def test_htmx_get_returns_the_panel_and_the_rows_not_a_page(client_as):
    mixed_order()

    response = client_as("Planner").get(CREATE, {"material": "RM-SHORT"}, **HTMX)

    html = response.content.decode()
    assert response.status_code == 200
    assert "<html" not in html
    assert "Review requisition" in html
    assert OOB_ROWS in html  # B-1: wrapped in <template>, after the panel
    assert html.index("Review requisition") < html.index(OOB_ROWS)
    assert selected_rows(html) == ["RM-SHORT"]
    assert "HX-Request" in response["Vary"]


@pytest.mark.parametrize("which", ["create", "empty", "outcome"])
def test_a_plain_request_gets_the_whole_order_page_without_oob(client_as, sent_to, resyncs, which):
    mixed_order()
    client_as("Planner").post(f"{CREATE}?material=RM-SHORT", {"quantity": "30"})
    pk = Requisition.objects.get().pk
    url = {"create": f"{CREATE}?material=RM-LOW", "empty": EMPTY, "outcome": f"{CREATE}{pk}/"}[
        which
    ]

    response = client_as("Planner").get(url)

    html = response.content.decode()
    assert response.status_code == 200
    assert "<html" in html and "<h1>Order 1000001</h1>" in html
    assert 'id="components-body"' in html
    assert "hx-swap-oob" not in html  # the page never carries it
    assert "HX-Request" in response["Vary"]


def test_review_shows_strip_field_date_plant_and_highlights_the_row(client_as):
    mixed_order()

    html = client_as("Planner").get(CREATE, {"material": "RM-LOW"}, **HTMX).content.decode()

    for text in ("Review requisition", "RM-LOW", "Shortage", "To 110% cover", "Sent to SAP"):
        assert text in html
    assert 'value="6"' in html and "Quantity (order unit PC)" in html
    assert "Delivery date" in html and "Plant" in html and "AUC1" in html
    assert "Cancel" in html and "Send requisition" in html
    assert selected_rows(html) == ["RM-LOW"]


def test_review_form_has_csrf_and_cancel_is_a_sibling_form(client_as):
    """I-2, R2-1: a plain Send carries its token; Cancel's URL has no token or quantity."""
    mixed_order()

    html = client_as("Planner").get(CREATE, {"material": "RM-SHORT"}, **HTMX).content.decode()

    review_form = re.search(r'<form id="requisition-form".*?</form>', html, re.S).group(0)
    assert "csrfmiddlewaretoken" in review_form
    assert "<form" not in review_form[1:]  # no nested form
    assert 'form="cancel-form"' in review_form
    cancel = re.search(r'<form id="cancel-form"[^>]*>', html).group(0)
    assert f'action="{EMPTY}"' in cancel
    assert "csrfmiddlewaretoken" not in cancel and "quantity" not in cancel


def test_request_buttons_work_without_javascript(client_as):
    """I-4: the form submits its hidden material, and hx-get keeps ?material=."""
    mixed_order()
    planner = client_as("Planner")
    page = planner.get(ORDER).content.decode()
    cell = row_of(page, "RM-SHORT")

    assert '<input type="hidden" name="material" value="RM-SHORT">' in cell
    assert f'hx-get="{CREATE}?material=RM-SHORT"' in cell
    action = re.search(r'<form method="get" action="([^"]+)"', cell).group(1)
    submitted = planner.get(action, {"material": "RM-SHORT"})  # what the browser sends
    assertContains(submitted, "Review requisition")


# --- Preview (P-5, I-1) --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("quantity", "shown"),
    [("12.5", "12.500 PC"), ("0", "–"), ("abc", "–"), ("1.2345", "–"), ("", "–")],
)
def test_preview_shows_the_sent_quantity_or_a_dash(client_as, quantity, shown):
    mixed_order()

    response = client_as("Planner").get(
        PREVIEW, {"material": "RM-SHORT", "quantity": quantity}, **HTMX
    )

    assert response.status_code == 200
    assert response.content.decode().strip() == shown


def test_preview_converts_to_the_stock_unit(client_as, sent_to):
    add_order("1000001", START, [("0001", "RM-KG", "2", "KG")])
    add_stock("RM-KG", "1500", unit="G")

    response = client_as("Planner").get(PREVIEW, {"material": "RM-KG", "quantity": "0.5"}, **HTMX)

    assert response.content.decode().strip() == "500.000 G"
    assert sent_to.payloads == []  # a preview sends and stores nothing
    assert Requisition.objects.count() == 0


@pytest.mark.parametrize("material", ["RM-COVER", "RM-NOPE"])
def test_preview_of_a_refused_material_is_a_dash_with_200(client_as, material):
    mixed_order()

    response = client_as("Planner").get(PREVIEW, {"material": material, "quantity": "5"}, **HTMX)

    assert (response.status_code, response.content.decode().strip()) == (200, "–")


def test_a_plain_get_of_the_preview_shows_the_review_page(client_as):
    mixed_order()

    response = client_as("Planner").get(PREVIEW, {"material": "RM-SHORT", "quantity": "5"})

    assertContains(response, "<h1>Order 1000001</h1>")
    assertContains(response, "Review requisition")


# --- Send: outcomes (P-3) ------------------------------------------------------------------------


def test_sending_shows_pr_sent_and_updates_the_label_in_the_same_response(
    client_as, sent_to, resyncs
):
    mixed_order()

    response = client_as("Planner").post(f"{CREATE}?material=RM-SHORT", {"quantity": "30"}, **HTMX)

    html = response.content.decode()
    assert response.status_code == 200
    assert "PR sent" in html and "10000000" in html and "30 PC" in html
    assert html.index("PR number") < html.index(OOB_ROWS)
    assert "PR sent</button>" in row_of(html, "RM-SHORT")  # the label replaced the button
    assert "Request</button>" in row_of(html, "RM-LOW")
    assert selected_rows(html) == ["RM-SHORT"]


def test_a_failed_send_shows_the_error_the_escaped_details_and_retry(client_as, sent_to, resyncs):
    mixed_order()
    sent_to.answer = RequisitionResult(None, "Material <b>blocked</b>.", {"status": 400})

    html = (
        client_as("Planner")
        .post(f"{CREATE}?material=RM-SHORT", {"quantity": "30"}, **HTMX)
        .content.decode()
    )

    assert "PR failed" in html
    assert "Material &lt;b&gt;blocked&lt;/b&gt;." in html
    assert "Request and response" in html and "&quot;RequestedQuantity&quot;" in html
    assert f'hx-get="{CREATE}?material=RM-SHORT"' in html  # Retry
    assert "PR failed</button>" in row_of(html, "RM-SHORT")


def test_invalid_quantity_shows_the_message_under_the_field(client_as, sent_to):
    mixed_order()

    response = client_as("Planner").post(
        f"{CREATE}?material=RM-SHORT", {"quantity": "1.2345"}, **HTMX
    )

    html = response.content.decode()
    assert response.status_code == 200
    assert "Use at most 3 decimals." in html and 'value="1.2345"' in html
    assert sent_to.payloads == [] and Requisition.objects.count() == 0


def test_duplicate_and_not_requestable_show_in_the_panel(client_as, sent_to, resyncs):
    mixed_order()
    planner = client_as("Planner")
    planner.post(f"{CREATE}?material=RM-SHORT", {"quantity": "30"})
    reference = Requisition.objects.get().reference

    duplicate = planner.post(f"{CREATE}?material=RM-SHORT", {"quantity": "30"}, **HTMX)
    covered = planner.get(CREATE, {"material": "RM-COVER"}, **HTMX)

    assert duplicate.status_code == 409
    assertContains(duplicate, f"already open ({reference})", status_code=409)
    assert covered.status_code == 400
    assertContains(covered, "not short or low on cover", status_code=400)
    assert len(sent_to.payloads) == 1


def test_unknown_order_or_material_is_a_404(client_as):
    mixed_order()
    planner = client_as("Planner")

    assert planner.get(CREATE, {"material": "RM-NOPE"}, **HTMX).status_code == 404
    assert planner.get("/orders/9999999/requisitions/panel/empty/", **HTMX).status_code == 404
    assert planner.get("/orders/9999999/requisitions/", {"material": "RM-SHORT"}).status_code == 404


# --- Outcome and Empty (P-4) ---------------------------------------------------------------------


def failed_requisition(client_as, sent_to):
    sent_to.answer = RequisitionResult(None, "SAP says no.", {"status": 400})
    client_as("Planner").post(f"{CREATE}?material=RM-SHORT", {"quantity": "30"})
    return Requisition.objects.get()


@pytest.mark.parametrize("role", ["Viewer", "Planner", "Manager"])
def test_every_business_role_can_open_an_outcome(client_as, sent_to, resyncs, role):
    mixed_order()
    requisition = failed_requisition(client_as, sent_to)

    html = client_as(role).get(f"{CREATE}{requisition.pk}/", **HTMX).content.decode()

    assert "PR failed" in html and "SAP says no." in html and "Request and response" in html
    assert selected_rows(html) == ["RM-SHORT"]
    assert ("Retry</button>" in html) is (role != "Viewer")  # a Viewer never sees Retry


def test_an_outcome_of_another_order_is_a_404(client_as, sent_to, resyncs):
    mixed_order()
    add_order("1000002", START, [("0001", "RM-OTHER", "1", "PC")])
    requisition = failed_requisition(client_as, sent_to)

    response = client_as("Viewer").get(f"/orders/1000002/requisitions/{requisition.pk}/", **HTMX)

    assert response.status_code == 404


def test_empty_state_clears_the_highlight(client_as):
    mixed_order()

    html = client_as("Viewer").get(EMPTY, **HTMX).content.decode()

    assert "Choose Request on a short or low-cover component" in html
    assert selected_rows(html) == []
    assert OOB_ROWS in html


# --- Roles (P-8, INV-1) --------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["Viewer", "Admin"])
@pytest.mark.parametrize("url", [CREATE, PREVIEW])
def test_create_and_preview_are_for_planner_and_manager_only(client_as, sent_to, role, url):
    mixed_order()

    response = client_as(role).get(url, {"material": "RM-SHORT", "quantity": "5"}, **HTMX)

    assert response.status_code == 403
    assert Requisition.objects.count() == 0


def test_admin_gets_403_on_the_outcome_and_empty_urls(client_as):
    mixed_order()
    admin = client_as("Admin")

    assert admin.get(EMPTY, **HTMX).status_code == 403
    assert admin.get(f"{CREATE}1/", **HTMX).status_code == 403


def test_viewer_sees_dashes_the_note_and_a_clickable_label(client_as, sent_to, resyncs):
    mixed_order()
    requisition = failed_requisition(client_as, sent_to)

    page = client_as("Viewer").get(ORDER)

    assertContains(page, "You can view requisitions but not create them.")
    assertNotContains(page, "Request</button>")
    assertContains(page, f'hx-get="{CREATE}{requisition.pk}/"')
    assert "–" in row_of(page.content.decode(), "RM-LOW")


def test_a_direct_post_as_viewer_is_refused_and_a_post_needs_csrf(sent_to):
    """INV-1 and I-2: the plain Send POST is protected by the CSRF token."""
    mixed_order()
    client = Client(enforce_csrf_checks=True)

    assert client.post(f"{CREATE}?material=RM-SHORT", {"quantity": "30"}).status_code in (302, 403)
    assert sent_to.payloads == []


@pytest.mark.parametrize("number", ["1000001%00", "9" * 41])
@pytest.mark.parametrize("path", ["", "preview/", "panel/empty/", "1/"])
def test_an_order_number_the_database_cannot_hold_is_a_404(client_as, number, path):
    """Like the order page (#77 review): a NUL byte or a too long number is a 404, not a 500."""
    mixed_order()
    planner = client_as("Planner")

    for headers in ({}, HTMX):
        response = planner.get(
            f"/orders/{number}/requisitions/{path}", {"material": "RM-SHORT"}, **headers
        )
        assert response.status_code == 404
    assert (
        planner.post(
            f"/orders/{number}/requisitions/?material=RM-SHORT", {"quantity": "5"}
        ).status_code
        == 404
    )
