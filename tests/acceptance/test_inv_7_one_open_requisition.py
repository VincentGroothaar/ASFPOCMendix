"""INV-7: at most one requisition per order + material that is awaiting approval or sent.
Database constraint: a second open one is refused even when written straight to the database.
Failed and rejected attempts do not count."""

import pytest
from django.db import IntegrityError, transaction

from tests.acceptance import builders
from tests.acceptance.support import MIXED_ORDER, load_mixed_order, sync

pytestmark = pytest.mark.xfail(strict=True, reason="Not built yet: #24 (sync); the model is #21")

OPEN = [builders.AWAITING_APPROVAL, builders.SENT]


@pytest.mark.parametrize("first", OPEN)
@pytest.mark.parametrize("second", OPEN)
def test_inv_7_database_refuses_a_second_open_requisition(fakes, clock, first, second):
    load_mixed_order(fakes.sap)
    sync()
    user = builders.make_user("Planner")
    builders.store_requisition(MIXED_ORDER, "RM-SHORT", first, user)

    with pytest.raises(IntegrityError), transaction.atomic():
        builders.store_requisition(MIXED_ORDER, "RM-SHORT", second, user)


def test_inv_7_failed_and_rejected_attempts_do_not_block(fakes, clock):
    load_mixed_order(fakes.sap)
    sync()
    user = builders.make_user("Planner")

    builders.store_requisition(MIXED_ORDER, "RM-SHORT", builders.FAILED, user)
    builders.store_requisition(MIXED_ORDER, "RM-SHORT", builders.REJECTED, user)
    builders.store_requisition(MIXED_ORDER, "RM-SHORT", builders.SENT, user)
    builders.store_requisition(MIXED_ORDER, "RM-LOW", builders.SENT, user)

    assert len(builders.requisitions()) == 4
