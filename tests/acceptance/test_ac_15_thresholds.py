"""AC-15 (REQ-4): thresholds for requirement 100: available 99 → red (shortage 1);
100 → amber; 109.999 → amber; 110 → green. Unit test with Decimal (INV-5), buffer 10."""

from decimal import Decimal

import pytest

from tests.acceptance import builders
from tests.acceptance.support import Stock, days, one_component_order


@pytest.mark.parametrize(
    ("available", "status", "shortage"),
    [
        ("99", builders.SHORT, Decimal("1")),
        ("100", builders.LOW_COVER, Decimal("0")),
        ("109.999", builders.LOW_COVER, Decimal("0")),
        ("110", builders.COVERED, Decimal("0")),
    ],
)
def test_ac_15_status_thresholds_for_requirement_100(available, status, shortage):
    order = one_component_order("1000001", days(1), "RM-1", "100")

    outcome = builders.calculate([order], [Stock("RM-1", Decimal(available))])

    component = outcome.component("1000001")
    assert component.status == status
    assert (component.shortage or Decimal("0")) == shortage
