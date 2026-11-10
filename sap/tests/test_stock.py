"""Tests for reading unrestricted-use stock (REQ-3, AC-12)."""

from decimal import Decimal

import pytest

from sap.client import SapDataError
from sap.stock import UNRESTRICTED_FILTER, MaterialStock, read_unrestricted_stock
from sap.tests.fake_http import FakeSap, client_for


def stock_row(
    quantity: str,
    material: str = "RM-1",
    location: str = "0001",
    stock_type: str = "01",
    special: str = "",
    plant: str = "AUC1",
    unit: str = "PC",
) -> dict:
    return {
        "Material": material,
        "Plant": plant,
        "StorageLocation": location,
        "InventoryStockType": stock_type,
        "InventorySpecialStockType": special,
        "MatlWrhsStkQtyInMatlBaseUnit": quantity,
        "MaterialBaseUnit": unit,
    }


MIXED_ROWS = [
    stock_row("30", location="0001"),
    stock_row("20.5", location="0002"),
    stock_row("100", stock_type="02"),  # quality inspection
    stock_row("100", stock_type="07"),  # blocked
    stock_row("100", special="E"),  # sales order stock
    stock_row("100", special="K"),  # consignment
    stock_row("100", plant="USC1"),  # another plant
    stock_row("7", material="RM-2"),
]


def test_sums_unrestricted_stock_over_storage_locations_only() -> None:
    sap = FakeSap(rows={"A_MatlStkInAcctMod": MIXED_ROWS})

    stock = read_unrestricted_stock(client_for(sap), "AUC1", ["RM-1", "RM-2"])

    assert stock == {
        "RM-1": MaterialStock("RM-1", Decimal("50.5"), "PC"),
        "RM-2": MaterialStock("RM-2", Decimal("7"), "PC"),
    }


def test_asks_sap_only_for_unrestricted_non_special_stock_of_the_materials() -> None:
    sap = FakeSap(rows={"A_MatlStkInAcctMod": MIXED_ROWS})

    read_unrestricted_stock(client_for(sap), "AUC1", ["RM-2", "RM-1"])

    [call] = sap.calls
    assert call.path.endswith("/API_MATERIAL_STOCK_SRV/A_MatlStkInAcctMod")
    assert call.param("$filter") == (
        "Plant eq 'AUC1' and InventoryStockType eq '01' and InventorySpecialStockType eq '' "
        "and (Material eq 'RM-1' or Material eq 'RM-2')"
    )
    assert UNRESTRICTED_FILTER in call.param("$filter")


def test_ignores_excluded_rows_even_if_sap_sends_them() -> None:
    # SAP sends every row here: the read function must still count only unrestricted stock.
    sap = FakeSap(rows={"A_MatlStkInAcctMod": MIXED_ROWS}, apply_filter=False)

    stock = read_unrestricted_stock(client_for(sap), "AUC1", ["RM-1"])

    assert stock == {"RM-1": MaterialStock("RM-1", Decimal("50.5"), "PC")}


def test_material_without_stock_rows_is_left_out() -> None:
    sap = FakeSap(rows={"A_MatlStkInAcctMod": MIXED_ROWS})

    stock = read_unrestricted_stock(client_for(sap), "AUC1", ["RM-1", "RM-NONE"])

    assert set(stock) == {"RM-1"}


def test_reads_materials_in_batches_of_40() -> None:
    materials = [f"RM-{n:03}" for n in range(85)]
    rows = [stock_row("1", material=material) for material in materials]
    sap = FakeSap(rows={"A_MatlStkInAcctMod": rows})

    stock = read_unrestricted_stock(client_for(sap), "AUC1", materials + materials[:3])

    assert len(stock) == 85
    assert [call.param("$filter").count("Material eq") for call in sap.calls] == [40, 40, 5]


def test_no_materials_means_no_calls() -> None:
    sap = FakeSap(rows={"A_MatlStkInAcctMod": MIXED_ROWS})

    assert read_unrestricted_stock(client_for(sap), "AUC1", []) == {}
    assert sap.calls == []


def test_stock_of_one_material_in_two_units_raises_sap_data_error() -> None:
    rows = [stock_row("1", unit="KG"), stock_row("1000", location="0002", unit="G")]
    sap = FakeSap(rows={"A_MatlStkInAcctMod": rows})

    with pytest.raises(SapDataError, match="both KG and G"):
        read_unrestricted_stock(client_for(sap), "AUC1", ["RM-1"])


def test_quantity_that_is_not_a_number_raises_sap_data_error() -> None:
    sap = FakeSap(rows={"A_MatlStkInAcctMod": [stock_row("lots")]})

    with pytest.raises(SapDataError):
        read_unrestricted_stock(client_for(sap), "AUC1", ["RM-1"])
