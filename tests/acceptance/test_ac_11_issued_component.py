"""AC-11 (REQ-2): a component with open requirement 0 shows "issued" and has no status.
Unit test: the sandbox has no issued components in AUC1."""

from decimal import Decimal

import pytest

from tests.acceptance import builders
from tests.acceptance.support import Component, Order, Stock, days

pytestmark = pytest.mark.xfail(strict=True, reason="Not built yet: #20")


def test_ac_11_fully_withdrawn_component_is_issued_and_does_not_count():
    order = Order(
        "1000101",
        days(1),
        [
            Component("RM-1", Decimal("5"), withdrawn=Decimal("5"), item="0001"),
            Component("RM-2", Decimal("10"), item="0002"),
        ],
    )

    outcome = builders.calculate([order], [Stock("RM-2", Decimal("100"))])

    assert outcome.component("1000101", "0001").status == builders.ISSUED
    assert outcome.orders["1000101"].status == builders.COVERED
