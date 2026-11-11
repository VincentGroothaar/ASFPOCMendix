"""AC-16 (REQ-4): the buffer is not taken from stock. Stock 215, orders A and B each need
100 → A available 215, green; B available 115 (not 105), green."""

from decimal import Decimal

from tests.acceptance import builders
from tests.acceptance.support import Stock, days, one_component_order


def test_ac_16_only_the_requirement_is_subtracted_not_the_buffer():
    orders = [
        one_component_order("1000001", days(1), "RM-1", "100"),
        one_component_order("1000002", days(2), "RM-1", "100"),
    ]

    outcome = builders.calculate(orders, [Stock("RM-1", Decimal("215"))])

    a = outcome.component("1000001")
    b = outcome.component("1000002")
    assert (a.status, a.available) == (builders.COVERED, Decimal("215"))
    assert (b.status, b.available) == (builders.COVERED, Decimal("115"))
