"""AC-25 (REQ-5): on an endpoint error the error message is shown, the attempt is stored as
failed, and Retry creates a new attempt.

The fake mock answers with the mock's own 400 error body (decision 5 on #15): the app cannot
be made to send an invalid requisition on purpose.
"""

from decimal import Decimal

from tests.acceptance import builders
from tests.acceptance.support import MIXED_ORDER, load_mixed_order, read_page, sync

MESSAGE = "Property 'PurchasingGroup' is required (item 1)."


def test_ac_25_error_is_shown_stored_as_failed_and_retry_makes_a_new_attempt(
    fakes, clock, client_as
):
    load_mixed_order(fakes.sap)
    for stock in fakes.sap.stock:
        stock.price = Decimal("1")
    planner = client_as("Planner")
    sync()
    create = f"/orders/{MIXED_ORDER}/requisitions/?material=RM-SHORT"
    fakes.mock.error = MESSAGE

    response = planner.post(create, builders.requisition_form("30"), follow=True)

    assert MESSAGE in read_page(response).text
    [failed] = builders.requisitions()
    assert failed.status == builders.FAILED
    assert "PR failed" in read_page(planner.get(f"/orders/{MIXED_ORDER}/")).row_with("RM-SHORT")

    fakes.mock.error = None
    planner.post(create, builders.requisition_form("30"))  # Retry uses the same endpoint

    assert [r.status for r in builders.requisitions()] == [builders.FAILED, builders.SENT]
