"""Tests for the requisition endpoint /orders/<n>/requisitions/?material= (#27, R-3; #28 panel)."""

import pytest
from pytest_django.asserts import assertContains, assertTemplateUsed

from cockpit.models import Requisition
from cockpit.tests.test_requisitions import mixed_order, resyncs, sent_to  # noqa: F401 (fixtures)

URL = "/orders/1000001/requisitions/"


@pytest.fixture(autouse=True)
def no_sap(settings):
    """No SAP connection, so the full page's sync never leaves the test (and stores nothing)."""
    settings.SAP_BASE_URL = ""


@pytest.mark.django_db
def test_confirm_step_shows_the_prefilled_form(client_as):
    mixed_order()

    response = client_as("Planner").get(URL, {"material": "RM-SHORT"})

    assert response.status_code == 200
    assertTemplateUsed(response, "cockpit/orders/panel/review.html")
    assertContains(response, 'name="quantity"')
    assertContains(response, 'value="30"')
    assertContains(response, "Quantity (order unit PC)")
    assertContains(response, "Send requisition")


@pytest.mark.django_db
def test_low_cover_shows_the_cover_target(client_as):
    mixed_order()

    response = client_as("Planner").get(URL, {"material": "RM-LOW"})

    assertContains(response, "To 110% cover")


@pytest.mark.django_db
@pytest.mark.parametrize("method", ["get", "post"])
@pytest.mark.parametrize("role", ["Viewer", "Admin"])
def test_viewer_and_admin_get_403(client_as, sent_to, method, role):  # noqa: F811
    mixed_order()

    data = {"quantity": "30"} if method == "post" else None
    response = getattr(client_as(role), method)(f"{URL}?material=RM-SHORT", data)

    assert response.status_code == 403
    assert Requisition.objects.count() == 0


@pytest.mark.django_db
def test_sent_requisition_shows_the_result(client_as, sent_to, resyncs):  # noqa: F811
    mixed_order()

    response = client_as("Planner").post(f"{URL}?material=RM-SHORT", {"quantity": "30"})

    assert response.status_code == 200
    assertTemplateUsed(response, "cockpit/orders/panel/sent.html")
    requisition = Requisition.objects.get()
    assertContains(response, requisition.reference)
    assertContains(response, "PR sent")
    assertContains(response, "10000000")


@pytest.mark.django_db
def test_failed_requisition_shows_the_error_and_retry(client_as, sent_to, resyncs):  # noqa: F811
    from sap.requisitions import RequisitionResult

    mixed_order()
    sent_to.answer = RequisitionResult(None, "Material <b>blocked</b>.", {})

    response = client_as("Planner").post(f"{URL}?material=RM-SHORT", {"quantity": "30"})

    assert response.status_code == 200
    assertContains(response, "PR failed")
    assertContains(response, "Material &lt;b&gt;blocked&lt;/b&gt;.")  # SAP text is escaped
    assertContains(response, f'hx-get="{URL}?material=RM-SHORT"')
    assertContains(response, '<input type="hidden" name="material" value="RM-SHORT">', html=True)


@pytest.mark.django_db
def test_invalid_quantity_shows_the_form_again(client_as, sent_to):  # noqa: F811
    mixed_order()

    response = client_as("Planner").post(f"{URL}?material=RM-SHORT", {"quantity": "1.2345"})

    assert response.status_code == 200
    assertContains(response, "Use at most 3 decimals.")
    assertContains(response, 'value="1.2345"')
    assert sent_to.payloads == []


@pytest.mark.django_db
def test_duplicate_shows_the_form_with_409(client_as, sent_to, resyncs):  # noqa: F811
    mixed_order()
    client = client_as("Planner")
    client.post(f"{URL}?material=RM-SHORT", {"quantity": "30"})

    response = client.post(f"{URL}?material=RM-SHORT", {"quantity": "30"})

    assert response.status_code == 409
    first = Requisition.objects.get()
    assertContains(response, f"already open ({first.reference})", status_code=409)
    assert len(sent_to.payloads) == 1


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("path", "material", "status"),
    [
        (URL, "RM-COVER", 400),  # R-3: not short or low cover
        (URL, "RM-NOPE", 404),
        ("/orders/9999999/requisitions/", "RM-SHORT", 404),
    ],
)
@pytest.mark.parametrize("method", ["get", "post"])
def test_not_requestable_or_unknown(client_as, sent_to, path, material, status, method):  # noqa: F811
    mixed_order()

    # On a GET the test client would replace the query string with the data, so send none.
    data = {"quantity": "30"} if method == "post" else None
    response = getattr(client_as("Planner"), method)(f"{path}?material={material}", data)

    assert response.status_code == status
    assert Requisition.objects.count() == 0
    assert sent_to.payloads == []
