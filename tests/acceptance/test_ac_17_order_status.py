"""AC-17 (REQ-4): an order's status is its worst component status; unit mismatch alone gives a
warning badge, not red. Unit test: order-level amber never occurs alone in the sandbox."""

from decimal import Decimal

import pytest

from tests.acceptance import builders
from tests.acceptance.support import Component, Order, Stock, days

STOCK = [
    Stock("RM-SHORT", Decimal("50")),
    Stock("RM-LOW", Decimal("105")),
    Stock("RM-COVER", Decimal("500")),
    Stock("RM-KG", Decimal("500"), unit="KG"),
]


def order_with(*materials: str) -> Order:
    lines = [
        Component(material, Decimal("100"), item=f"000{position}")
        for position, material in enumerate(materials, start=1)
    ]
    return Order("1000001", days(1), lines)


@pytest.mark.parametrize(
    ("materials", "status"),
    [
        (("RM-COVER", "RM-SHORT", "RM-LOW"), builders.SHORT),
        (("RM-COVER", "RM-LOW"), builders.LOW_COVER),
        (("RM-COVER",), builders.COVERED),
    ],
)
def test_ac_17_order_status_is_the_worst_component_status(materials, status):
    outcome = builders.calculate([order_with(*materials)], STOCK)

    assert outcome.orders["1000001"].status == status


def test_ac_17_unit_mismatch_gives_a_badge_not_red():
    # RM-KG is needed in PC but stocked in KG: a mismatch.
    outcome = builders.calculate([order_with("RM-COVER", "RM-KG")], STOCK)

    assert outcome.component("1000001", "0002").status == builders.UNIT_MISMATCH
    assert outcome.orders["1000001"].status == builders.COVERED
    assert outcome.orders["1000001"].unit_mismatch is True
