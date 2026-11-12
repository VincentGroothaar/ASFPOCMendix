"""Tests for the requisition list and the requisition detail page (REQ-5, #29: AC-56 to AC-62)."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from pytest_django.asserts import assertContains, assertNotContains

from cockpit.models import Component, ProductionOrder, Requisition
from cockpit.services import requisition_views

Status = Requisition.Status
LIST_URL = "/requisitions/"
BASE_TIME = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)  # 10:00 in the app time zone


@pytest.fixture
def order(db) -> ProductionOrder:
    order = ProductionOrder.objects.create(
        number="1000001",
        plant="AUC1",
        material="FG-1",
        quantity=Decimal("10"),
        unit="PC",
        start_date=date(2026, 11, 4),
        synced_at=BASE_TIME,
    )
    Component.objects.create(
        order=order,
        item="0010",
        material="RM-1",
        description="Steel plate",
        required_quantity=Decimal("10"),
        withdrawn_quantity=Decimal("0"),
        unit="PC",
    )
    return order


def make(order: ProductionOrder, user: User, status: str = Status.SENT, **fields) -> Requisition:
    """A requisition with sensible defaults; `fields` override any of them."""
    values = {
        "order": order,
        "material": "RM-1",
        "items": "0010",
        "quantity_entered": Decimal("6"),
        "unit_entered": "PC",
        "quantity_sent": Decimal("6"),
        "unit_sent": "PC",
        "shortage_at_request": Decimal("6"),
        "delivery_date": date(2026, 11, 4),
        "status": status,
        "pr_number": "10000001" if status == Status.SENT else "",
        "created_by": user,
        "created_at": BASE_TIME,
    }
    values.update(fields)
    return Requisition.objects.create(**values)


@pytest.fixture
def pat(make_user) -> User:
    return make_user("Planner", username="pat")


# --- List: AC-26, AC-56 -------------------------------------------------------------------------


def test_list_shows_the_business_fields_of_each_attempt(client_as, order, pat):
    sent = make(order, pat)
    failed = make(order, pat, Status.FAILED, material="RM-2", error_message="Blocked.")

    response = client_as("Viewer").get(LIST_URL)

    assertContains(response, sent.reference)
    assertContains(response, "PR 10000001")
    assertContains(response, "Steel plate")
    assertContains(response, "6.000 PC")
    assertContains(response, "04 Nov")
    assertContains(response, "1000001")
    assertContains(response, "pat")
    assertContains(response, "03 Nov 10:00")
    assertContains(response, failed.reference)
    assertContains(response, "No PR number yet")
    assertContains(response, "PR failed")


def test_rejected_row_says_no_pr_number(client_as, order, pat):
    make(order, pat, Status.REJECTED)

    response = client_as("Viewer").get(LIST_URL)

    assertContains(response, "No PR number<")
    assertNotContains(response, "No PR number yet")


def test_list_is_newest_first_and_paged_by_50(client_as, order, pat):
    for index in range(51):
        make(order, pat, Status.FAILED, created_at=BASE_TIME + timedelta(minutes=index))
    newest, oldest = (
        Requisition.objects.order_by("-created_at").first(),
        Requisition.objects.first(),
    )

    first_page = client_as("Viewer").get(LIST_URL)
    second_page = client_as("Viewer").get(LIST_URL, {"page": "2"})

    assertContains(first_page, "Showing 50 of 51 requisitions")
    assertContains(first_page, f">{newest.reference}<")
    assertNotContains(first_page, f">{oldest.reference}<")
    assertContains(second_page, "Showing 1 of 51 requisitions")
    assertContains(second_page, f">{oldest.reference}<")


def test_empty_list_says_so(client_as, order):
    response = client_as("Viewer").get(LIST_URL)

    assertContains(response, "No requisitions yet.")


# --- Filters and paging: AC-57 ------------------------------------------------------------------


@pytest.mark.parametrize("status", [s.value for s in Status])
def test_status_filter_shows_only_that_status(client_as, order, pat, status):
    rows = {s: make(order, pat, s, material=f"M-{s}") for s in Status}

    response = client_as("Viewer").get(LIST_URL, {"status": status})

    for other, requisition in rows.items():
        present = f">{requisition.reference}<" in response.content.decode()
        assert present == (other == status)


def test_only_mine_shows_the_users_own_attempts(client_as, make_user, order, pat):
    user = make_user("Planner", username="me")
    client = client_as("Planner")
    # client_as made its own user; find it as the newest user.
    current = User.objects.order_by("-id").first()
    mine = make(order, current, material="M-1")
    theirs = make(order, user, Status.FAILED, material="M-2")

    response = client.get(LIST_URL, {"mine": "1"})

    assertContains(response, f">{mine.reference}<")
    assertNotContains(response, f">{theirs.reference}<")
    assertContains(response, ">Clear<")


def test_invalid_status_is_ignored_and_clear_hides_with_no_filter(client_as, order, pat):
    make(order, pat)

    response = client_as("Viewer").get(LIST_URL, {"status": "bogus"})

    assertContains(response, "REQ-")
    assertNotContains(response, ">Clear<")


@pytest.mark.parametrize(
    ("raw", "expected_first_shown"),
    [("abc", 1), ("", 1), ("0", 1), ("-3", 1), ("999", 2)],
)
def test_bad_page_numbers_are_clamped(client_as, order, pat, raw, expected_first_shown):
    for index in range(51):
        make(order, pat, Status.FAILED, created_at=BASE_TIME + timedelta(minutes=index))

    response = client_as("Viewer").get(LIST_URL, {"page": raw})

    assert response.status_code == 200
    shown = 50 if expected_first_shown == 1 else 1
    assertContains(response, f"Showing {shown} of 51")


def test_page_on_an_empty_list_is_fine(client_as, order):
    response = client_as("Viewer").get(LIST_URL, {"page": "5"})

    assert response.status_code == 200
    assertContains(response, "No requisitions yet.")


# --- List shows no technical data: AC-58 --------------------------------------------------------


def test_list_never_shows_payload_response_or_error(client_as, order, pat):
    make(
        order,
        pat,
        Status.FAILED,
        payload={"Material": "SECRET-PAYLOAD"},
        response={"error": "SECRET-RESPONSE"},
        error_message="SECRET-ERROR",
    )

    response = client_as("Viewer").get(LIST_URL)

    for text in ("SECRET-PAYLOAD", "SECRET-RESPONSE", "SECRET-ERROR"):
        assertNotContains(response, text)


# --- Detail: AC-59 ------------------------------------------------------------------------------


def detail(client, requisition: Requisition):
    return client.get(f"/requisitions/{requisition.pk}/")


def test_sent_detail_shows_header_summary_details_and_progress(client_as, order, pat):
    requisition = make(order, pat, sent_at=BASE_TIME + timedelta(minutes=1))

    response = detail(client_as("Viewer"), requisition)

    assertContains(response, requisition.reference)
    assertContains(response, "RM-1 · Steel plate · PR 10000001")
    for text in ("Requested", "Shortage when requested", "Needed by", "04 Nov 2026"):
        assertContains(response, text)
    assertNotContains(response, "Value / limit")
    for text in ("Progress", "Sent to SAP", "10000001 · 03 Nov 10:01", "pat · 03 Nov 10:00"):
        assertContains(response, text)
    for text in ("Details", "Plant", "AUC1", "Quantity sent to SAP", "6.000 PC", "item 0010"):
        assertContains(response, text)
    assertNotContains(response, "Approved")


def test_breadcrumb_links_back_to_the_list(client_as, order, pat):
    requisition = make(order, pat)

    response = detail(client_as("Viewer"), requisition)

    assertContains(response, 'href="/requisitions/"')


def test_awaiting_detail_shows_a_waiting_approval_step(client_as, order, pat):
    requisition = make(order, pat, Status.AWAITING_APPROVAL)

    response = detail(client_as("Viewer"), requisition)

    assertContains(response, "Manager approval")
    assertContains(response, "step-waiting")
    assertContains(response, "step-not_reached")
    assertContains(response, "No PR number yet")


def test_failed_detail_shows_the_stored_error_as_is(client_as, order, pat):
    requisition = make(order, pat, Status.FAILED, error_message="Property 'X' is required.")

    response = detail(client_as("Viewer"), requisition)

    assertContains(response, "step-failed")
    assertContains(response, "Property &#x27;X&#x27; is required.")
    assertContains(response, "error-note")


def test_rejected_detail_shows_who_and_the_reason(client_as, make_user, order, pat):
    manager = make_user("Manager", username="mia")
    requisition = make(
        order,
        pat,
        Status.REJECTED,
        decided_by=manager,
        decided_at=BASE_TIME + timedelta(hours=1),
        reject_reason="Too expensive.",
    )

    response = detail(client_as("Viewer"), requisition)

    assertContains(response, "Rejected")
    assertContains(response, "mia · 03 Nov 11:00")
    assertContains(response, "Reason: Too expensive.")
    assertNotContains(response, "Sent to SAP")


@pytest.mark.parametrize("status", [Status.SENT, Status.FAILED])
def test_approved_step_shows_before_the_outcome(client_as, make_user, order, pat, status):
    manager = make_user("Manager", username="mia")
    requisition = make(
        order, pat, status, decided_by=manager, decided_at=BASE_TIME + timedelta(hours=1)
    )

    content = detail(client_as("Viewer"), requisition).content.decode()

    assert content.index("Approved") < content.index("Sent to SAP")
    assert "mia · 03 Nov 11:00" in content


def test_missing_shortage_shows_a_dash(client_as, order, pat):
    requisition = make(order, pat, shortage_at_request=None)

    response = detail(client_as("Viewer"), requisition)

    assertContains(response, "–")


def test_unknown_requisition_is_404(client_as, order):
    assert client_as("Viewer").get("/requisitions/999/").status_code == 404


# --- Technical details: AC-60 -------------------------------------------------------------------


def test_sent_shows_technical_details_with_request_and_response(client_as, order, pat):
    requisition = make(
        order, pat, payload={"Material": "RM-1"}, response={"PurchaseRequisition": "10000001"}
    )

    response = detail(client_as("Viewer"), requisition)

    assertContains(response, "<details>")
    assertContains(response, "Technical details")
    assertContains(response, "Request and response")
    assertContains(response, "&quot;Material&quot;: &quot;RM-1&quot;")
    assertContains(response, "10000001")


@pytest.mark.parametrize("status", [Status.AWAITING_APPROVAL, Status.REJECTED])
def test_other_statuses_have_no_technical_details(client_as, order, pat, status):
    requisition = make(order, pat, status, payload={"Material": "RM-1"})

    response = detail(client_as("Viewer"), requisition)

    assertNotContains(response, "Technical details")


def test_failed_without_payload_or_response_shows_fallback_lines(client_as, order, pat):
    requisition = make(order, pat, Status.FAILED, payload=None, response={})

    response = detail(client_as("Viewer"), requisition)

    assertContains(response, "Technical details")
    assertContains(response, "Nothing was sent.")
    assertContains(response, "No response received.")


def test_technical_details_are_escaped(client_as, order, pat):
    requisition = make(order, pat, payload={"Note": "<script>alert(1)</script>"})

    response = detail(client_as("Viewer"), requisition)

    assertNotContains(response, "<script>alert(1)</script>")


# --- Retry: AC-61 -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("role", "shown"), [("Viewer", False), ("Planner", True), ("Manager", True)]
)
def test_retry_shows_per_role_on_a_failed_requisition(client_as, order, pat, role, shown):
    requisition = make(order, pat, Status.FAILED)

    response = detail(client_as(role), requisition)

    link = 'href="/orders/1000001/requisitions/?material=RM-1"'
    if shown:
        assertContains(response, link)
        assertContains(response, ">Retry<")
    else:
        assertNotContains(response, "Retry")


@pytest.mark.parametrize("status", [Status.SENT, Status.AWAITING_APPROVAL, Status.REJECTED])
def test_retry_never_shows_on_other_statuses(client_as, order, pat, status):
    requisition = make(order, pat, status)

    assertNotContains(detail(client_as("Planner"), requisition), "Retry")


@pytest.mark.parametrize("later", [Status.SENT, Status.AWAITING_APPROVAL, Status.FAILED])
def test_retry_hides_on_a_failed_row_with_a_later_attempt(client_as, order, pat, later):
    old = make(order, pat, Status.FAILED)
    make(order, pat, later)

    assertNotContains(detail(client_as("Planner"), old), "Retry")


def test_a_later_attempt_for_another_material_does_not_hide_retry(client_as, order, pat):
    old = make(order, pat, Status.FAILED)
    make(order, pat, Status.SENT, material="RM-2")

    assertContains(detail(client_as("Planner"), old), "Retry")


def test_retry_url_encodes_the_material(order, pat):
    requisition = make(order, pat, Status.FAILED, material="A&B 1")

    url = requisition_views.retry_url(pat, requisition)

    assert url == "/orders/1000001/requisitions/?material=A%26B+1"


# --- Access: AC-62 ------------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["Viewer", "Planner", "Manager"])
def test_business_roles_can_open_both_pages(client_as, order, pat, role):
    requisition = make(order, pat)
    client = client_as(role)

    assert client.get(LIST_URL).status_code == 200
    assert detail(client, requisition).status_code == 200


@pytest.mark.parametrize("who", [("Admin",), ()])
def test_admin_and_users_without_a_role_get_403(client_as, order, pat, who):
    requisition = make(order, pat)
    client = client_as(*who)

    assert client.get(LIST_URL).status_code == 403
    assert detail(client, requisition).status_code == 403


def test_anonymous_users_are_sent_to_login(client, order, pat):
    requisition = make(order, pat)

    for url in (LIST_URL, f"/requisitions/{requisition.pk}/"):
        response = client.get(url)
        assert response.status_code == 302
        assert response["Location"].startswith("/accounts/login/")
