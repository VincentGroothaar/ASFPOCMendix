"""AC-14 (REQ-4): stock is allocated by start date, then order number.
Stock 100, order A (3 Nov, needs 60), order B (4 Nov, needs 60) → A available 100, green;
B available 40, red, shortage 20. Equal start dates are ordered by order number."""

from datetime import date
from decimal import Decimal

import pytest

from tests.acceptance import builders
from tests.acceptance.support import Stock, one_component_order

pytestmark = pytest.mark.xfail(strict=True, reason="Not built yet: #20")


def test_ac_14_earlier_start_date_takes_stock_first():
    # B is listed first and has the lower number, to prove the start date decides.
    order_b = one_component_order("1000001", date(2026, 11, 4), "RM-1", "60")
    order_a = one_component_order("1000002", date(2026, 11, 3), "RM-1", "60")

    outcome = builders.calculate([order_b, order_a], [Stock("RM-1", Decimal("100"))])

    a = outcome.component("1000002")
    b = outcome.component("1000001")
    assert (a.status, a.available) == (builders.COVERED, Decimal("100"))
    assert (b.status, b.available, b.shortage) == (builders.SHORT, Decimal("40"), Decimal("20"))


def test_ac_14_equal_start_dates_go_by_order_number():
    later_number = one_component_order("1000002", date(2026, 11, 3), "RM-1", "60")
    earlier_number = one_component_order("1000001", date(2026, 11, 3), "RM-1", "60")

    outcome = builders.calculate([later_number, earlier_number], [Stock("RM-1", Decimal("100"))])

    assert outcome.component("1000001").available == Decimal("100")
    assert outcome.component("1000002").available == Decimal("40")
