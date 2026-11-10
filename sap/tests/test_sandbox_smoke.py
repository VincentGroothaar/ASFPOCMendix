"""Smoke test against the live SAP sandbox (read only).

Reads orders, components, stock and descriptions for the demo plant with the real client.
Skipped when SAP_API_KEY is not set, so it runs locally and wherever the key is configured.
The sandbox changes daily, so this checks shapes and rules, not counts.
"""

from decimal import Decimal

import pytest
from django.conf import settings

from sap.client import ODataClient
from sap.production_orders import read_released_orders
from sap.products import read_descriptions
from sap.stock import read_unrestricted_stock

PLANT = "AUC1"

pytestmark = pytest.mark.skipif(
    not (settings.SAP_BASE_URL and settings.SAP_API_KEY),
    reason="Needs SAP_BASE_URL and SAP_API_KEY for the live sandbox",
)


def test_reads_orders_components_stock_and_descriptions_for_the_plant() -> None:
    client = ODataClient.from_settings()

    orders = read_released_orders(client, PLANT)
    materials = sorted({line.material for order in orders for line in order.components})
    stock = read_unrestricted_stock(client, PLANT, materials)
    descriptions = read_descriptions(client, materials)

    assert orders, f"Expected released open orders in {PLANT}"
    assert all(order.plant == PLANT for order in orders)
    assert len({order.number for order in orders}) == len(orders)
    assert any(order.components for order in orders)
    for order in orders:
        for line in order.components:
            assert isinstance(line.required_quantity, Decimal)
            assert isinstance(line.withdrawn_quantity, Decimal)
    assert stock, "Expected unrestricted stock for the component materials"
    assert all(item.quantity >= 0 for item in stock.values())
    assert set(descriptions) == set(materials)
