"""AC-19 (REQ-4): 2 KG required with 1,500 G stock → red, shortage 0.5 KG; 10 PC required with
stock in KG → unit mismatch. Unit test: component and stock units always match in the sandbox."""

from decimal import Decimal

from tests.acceptance import builders
from tests.acceptance.support import Stock, days, one_component_order


def test_ac_19_converted_stock_gives_red_with_shortage_in_the_order_unit():
    order = one_component_order("1000001", days(1), "RM-1", "2", unit="KG")

    outcome = builders.calculate([order], [Stock("RM-1", Decimal("1500"), unit="G")])

    component = outcome.component("1000001")
    assert component.status == builders.SHORT
    assert component.available == Decimal("1.5")
    assert component.shortage == Decimal("0.5")


def test_ac_19_pieces_against_kilograms_is_a_unit_mismatch():
    order = one_component_order("1000001", days(1), "RM-1", "10", unit="PC")

    outcome = builders.calculate([order], [Stock("RM-1", Decimal("40"), unit="KG")])

    assert outcome.component("1000001").status == builders.UNIT_MISMATCH
