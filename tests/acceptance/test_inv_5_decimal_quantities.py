"""INV-5: quantities are Decimal end to end, never float. Boundary values (110.000 vs 109.999)
and a sum that floats get wrong: 0.3 − 0.1 is 0.19999999999999998 in float, which would make
the second component below Short instead of Low cover."""

from decimal import Decimal

import pytest

from tests.acceptance import builders
from tests.acceptance.support import Component, Order, Stock, days

pytestmark = pytest.mark.xfail(strict=True, reason="Not built yet: #20")


def test_inv_5_results_are_decimal_and_exact():
    order = Order(
        "1000001",
        days(1),
        [
            Component("RM-1", Decimal("0.1"), unit="KG", item="0001"),
            Component("RM-1", Decimal("0.2"), unit="KG", item="0002"),
        ],
    )

    outcome = builders.calculate([order], [Stock("RM-1", Decimal("0.3"), unit="KG")])

    second = outcome.component("1000001", "0002")
    assert isinstance(second.available, Decimal)
    assert second.available == Decimal("0.2")
    assert second.status == builders.LOW_COVER


@pytest.mark.parametrize(
    ("available", "status"), [("110.000", builders.COVERED), ("109.999", builders.LOW_COVER)]
)
def test_inv_5_boundary_at_110_percent(available, status):
    order = Order("1000001", days(1), [Component("RM-1", Decimal("100.000"))])

    outcome = builders.calculate([order], [Stock("RM-1", Decimal(available))])

    component = outcome.component("1000001")
    assert component.status == status
    assert isinstance(component.available, Decimal)
