"""AC-12 (REQ-3): stock is unrestricted-use stock summed over storage locations; inspection,
blocked and special stock are excluded.

First test: constructed SAP rows of every kind (the fake SAP applies the app's $filter like
the sandbox). Second test: on the live sandbox, the first order needing a material gets the
whole filtered SAP sum as available stock.
"""

from decimal import Decimal

from tests.acceptance.support import (
    PLANT,
    Stock,
    days,
    live_released_orders,
    one_component_order,
    read_live_sap,
    read_page,
    shows_quantity,
    sync,
)


def test_ac_12_only_unrestricted_non_special_stock_counts(fakes, clock, client_as):
    fakes.sap.orders.append(one_component_order("1000101", days(1), "RM-1", "500"))
    fakes.sap.stock += [
        Stock("RM-1", Decimal("30"), storage_location="0001"),
        Stock("RM-1", Decimal("20"), storage_location="0002"),
        Stock("RM-1", Decimal("100"), stock_type="02"),  # quality inspection
        Stock("RM-1", Decimal("100"), stock_type="07"),  # blocked
        Stock("RM-1", Decimal("100"), special_stock="E"),  # sales order stock
        Stock("RM-1", Decimal("100"), special_stock="K"),  # consignment
        Stock("RM-1", Decimal("100"), plant="USC1"),  # another plant
    ]

    sync()

    row = read_page(client_as("Viewer").get("/orders/1000101/")).row_with("RM-1")

    assert shows_quantity(row, Decimal("50"), "PC"), row  # Available
    assert shows_quantity(row, Decimal("450"), "PC"), row  # Shortage


def first_order_per_material(orders: list[dict]) -> dict[str, dict]:
    """For each material, the order that gets stock first (start date, then order number)."""
    first: dict[str, dict] = {}
    for order in sorted(
        orders, key=lambda o: (o["MfgOrderScheduledStartDate"], o["ManufacturingOrder"])
    ):
        for line in order["to_ProductionOrderComponent"]["results"]:
            first.setdefault(line["Material"], order)
    return first


def test_ac_12_shown_stock_equals_the_filtered_sap_sum(live_sap, client_as):
    material, order = sorted(first_order_per_material(live_released_orders(PLANT)).items())[0]
    rows = read_live_sap(
        "API_MATERIAL_STOCK_SRV/A_MatlStkInAcctMod",
        {
            "$filter": f"Plant eq '{PLANT}' and Material eq '{material}' and "
            "InventoryStockType eq '01' and InventorySpecialStockType eq ''"
        },
    )
    stock = sum((Decimal(row["MatlWrhsStkQtyInMatlBaseUnit"]) for row in rows), Decimal("0"))
    unit = rows[0]["MaterialBaseUnit"] if rows else "PC"
    client = client_as("Viewer")
    client.get("/orders/", {"plant": PLANT})

    page = read_page(client.get(f"/orders/{order['ManufacturingOrder']}/"))

    row = page.row_with(material)
    assert shows_quantity(row, stock, unit), f"Expected available {stock} {unit} in: {row}"
