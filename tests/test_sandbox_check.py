"""Tests for the sandbox data check script (issue #7). No SAP calls are made."""

from datetime import date
from decimal import Decimal

import pytest
import requests

from scripts import sandbox_check
from scripts.sandbox_check import (
    SapReader,
    UnitMismatch,
    calculate_statuses,
    component_status,
    convert,
    parse_odata_date,
    unrestricted_stock,
)


def make_order(number: str, start: str, components: list[tuple[str, str, str, str]]) -> dict:
    """Build an A_ProductionOrder_2 row. Components are (material, required, withdrawn, unit)."""
    millis = int((date.fromisoformat(start) - date(1970, 1, 1)).total_seconds() * 1000)
    odata_date = f"/Date({millis})/"
    return {
        "ManufacturingOrder": number,
        "ManufacturingOrderCategory": "10",
        "ManufacturingOrderType": "YBM1",
        "ProductionPlant": "AUC1",
        "Plant": "AUC1",
        "OrderIsPartiallyDelivered": "",
        "Material": "FG",
        "TotalQuantity": "1",
        "ProductionUnit": "PC",
        "MfgOrderScheduledStartDate": odata_date,
        "MfgOrderPlannedStartDate": odata_date,
        "to_ProductionOrderComponent": {
            "results": [
                {
                    "ManufacturingOrder": number,
                    "ReservationItem": "1",
                    "Material": material,
                    "Plant": "AUC1",
                    "RequiredQuantity": required,
                    "WithdrawnQuantity": withdrawn,
                    "BaseUnit": unit,
                    "ReservationIsFinallyIssued": False,
                    "MatlCompIsMarkedForDeletion": False,
                    "MaterialComponentIsPhantomItem": False,
                }
                for material, required, withdrawn, unit in components
            ]
        },
    }


def make_stock_row(material: str, quantity: str, stock_type="01", special="", unit="PC") -> dict:
    """Build an A_MatlStkInAcctMod row."""
    return {
        "Material": material,
        "Plant": "AUC1",
        "StorageLocation": "0001",
        "InventoryStockType": stock_type,
        "InventorySpecialStockType": special,
        "MaterialBaseUnit": unit,
        "MatlWrhsStkQtyInMatlBaseUnit": quantity,
    }


def test_parse_odata_date() -> None:
    assert parse_odata_date("/Date(1496707200000)/") == date(2017, 6, 6)
    assert parse_odata_date(" /Date(1496707200000+0000)/ ") == date(2017, 6, 6)
    assert parse_odata_date(None) is None
    assert parse_odata_date("") is None


@pytest.mark.parametrize("value", ["2017-06-06", "/Date()/", "/Date(abc)/", "Date(1)"])
def test_parse_odata_date_rejects_other_formats(value: str) -> None:
    with pytest.raises(ValueError, match="not an OData V2 date"):
        parse_odata_date(value)


def test_convert_same_dimension_is_exact() -> None:
    assert convert(Decimal("1500"), "G", "KG") == Decimal("1.5")
    assert convert(Decimal("2"), "TO", "KG") == Decimal("2000")
    assert convert(Decimal("10"), "PC", "PC") == Decimal("10")


@pytest.mark.parametrize(("from_unit", "to_unit"), [("PC", "KG"), ("KG", "L"), ("EA", "PC")])
def test_convert_other_units_is_a_mismatch(from_unit: str, to_unit: str) -> None:
    with pytest.raises(UnitMismatch):
        convert(Decimal("1"), from_unit, to_unit)


def test_unrestricted_stock_skips_other_stock_types_and_special_stock() -> None:
    rows = [
        make_stock_row("M1", "10"),
        make_stock_row("M1", "5"),  # second storage location
        make_stock_row("M1", "100", stock_type="02"),  # quality inspection
        make_stock_row("M1", "100", stock_type="07"),  # blocked
        make_stock_row("M1", "100", special="E"),  # sales order stock
        make_stock_row("M2", "100", stock_type="02"),
    ]
    assert unrestricted_stock(rows) == {"M1": (Decimal("15"), "PC")}


def test_unrestricted_stock_converts_rows_into_the_first_unit() -> None:
    rows = [make_stock_row("M1", "1000", unit="G"), make_stock_row("M1", "1", unit="KG")]
    assert unrestricted_stock(rows) == {"M1": (Decimal("2000"), "G")}


@pytest.mark.parametrize(
    ("available", "expected"),
    [("99", "red"), ("100", "amber"), ("109.999", "amber"), ("110", "green")],
)
def test_component_status_thresholds(available: str, expected: str) -> None:
    assert component_status(Decimal(available), Decimal("100")) == expected


def test_calculate_statuses_allocates_by_start_date() -> None:
    # Stock 100: the earlier order takes 60, the later one is left with 40 for 60.
    # The later order is listed first, so the input order is not what decides.
    orders = [
        make_order("1", "2026-11-04", [("M1", "60", "0", "PC")]),
        make_order("2", "2026-11-03", [("M1", "60", "0", "PC")]),
    ]
    result = calculate_statuses(orders, {"M1": (Decimal("100"), "PC")})
    assert result["order_status"] == {"2": "green", "1": "red"}
    assert result["competing_materials"] == 1


def test_calculate_statuses_breaks_ties_by_order_number_as_a_number() -> None:
    # Same start date: order 9 comes before order 10.
    orders = [
        make_order("10", "2026-11-03", [("M1", "60", "0", "PC")]),
        make_order("9", "2026-11-03", [("M1", "60", "0", "PC")]),
    ]
    result = calculate_statuses(orders, {"M1": (Decimal("100"), "PC")})
    assert result["order_status"] == {"9": "green", "10": "red"}


def test_calculate_statuses_puts_orders_without_start_date_last() -> None:
    orders = [
        make_order("1", "2026-11-03", [("M1", "60", "0", "PC")]),
        make_order("2", "2026-11-04", [("M1", "60", "0", "PC")]),
    ]
    orders[0]["MfgOrderScheduledStartDate"] = None
    result = calculate_statuses(orders, {"M1": (Decimal("100"), "PC")})
    assert result["order_status"] == {"2": "green", "1": "red"}


@pytest.mark.parametrize("red_line_first", [True, False])
def test_calculate_statuses_gives_an_order_its_worst_component_status(
    red_line_first: bool,
) -> None:
    # M1 is short, M2 is covered. Both line orders must give a red order.
    lines = [("M1", "10", "0", "PC"), ("M2", "10", "0", "PC")]
    if not red_line_first:
        lines.reverse()
    orders = [make_order("1", "2026-11-03", lines)]
    stock = {"M1": (Decimal("5"), "PC"), "M2": (Decimal("100"), "PC")}
    result = calculate_statuses(orders, stock)
    assert result["components"] == {"green": 1, "red": 1}
    assert result["order_status"] == {"1": "red"}


def test_calculate_statuses_lets_lines_of_one_order_take_stock_in_turn() -> None:
    # Two lines of the same material in one order: the second sees what the first left.
    orders = [make_order("1", "2026-11-03", [("M1", "60", "0", "PC"), ("M1", "60", "0", "PC")])]
    result = calculate_statuses(orders, {"M1": (Decimal("100"), "PC")})
    assert result["components"] == {"green": 1, "red": 1}


def test_calculate_statuses_takes_only_the_real_requirement_from_stock() -> None:
    # Stock 215, two orders need 100: the second has 115 left, not 105, so both are green.
    orders = [
        make_order("1", "2026-11-03", [("M1", "100", "0", "PC")]),
        make_order("2", "2026-11-04", [("M1", "100", "0", "PC")]),
    ]
    result = calculate_statuses(orders, {"M1": (Decimal("215"), "PC")})
    assert result["components"] == {"green": 2}


def test_calculate_statuses_counts_issued_and_mismatched_components() -> None:
    orders = [
        make_order(
            "1",
            "2026-11-03",
            [("M1", "5", "5", "PC"), ("M2", "10", "0", "PC"), ("M3", "2", "0", "KG")],
        ),
    ]
    stock = {"M2": (Decimal("1"), "KG"), "M3": (Decimal("1500"), "G")}
    result = calculate_statuses(orders, stock)
    assert result["components"] == {"issued": 1, "unit mismatch": 1, "red": 1}
    assert result["orders"] == {"red + unit mismatch": 1}


def test_calculate_statuses_labels_an_order_with_only_mismatches() -> None:
    orders = [make_order("1", "2026-11-03", [("M1", "10", "0", "PC")])]
    result = calculate_statuses(orders, {"M1": (Decimal("1"), "KG")})
    assert result["order_status"] == {"1": "unit mismatch only"}


class FakeResponse:
    """Stands in for requests.Response with a fixed JSON body."""

    status_code = 200

    def __init__(self, body: dict) -> None:
        self._body = body
        self.text = ""
        self.content = b""

    def json(self) -> dict:
        return self._body

    def raise_for_status(self) -> None:
        pass


def test_check_plant_only_sends_get_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[str] = []
    order = make_order("1", "2026-11-03", [("M1", "60", "0", "PC")])
    bodies = {
        "API_PRODUCTION_ORDER_2_SRV/A_ProductionOrder_2": [order],
        "API_MATERIAL_STOCK_SRV/A_MatlStkInAcctMod": [make_stock_row("M1", "50")],
        "API_PRODUCT_SRV/A_ProductDescription": [{"Product": "M1", "ProductDescription": "One"}],
    }

    def fake_get(url: str, **kwargs) -> FakeResponse:
        sent.append(url)
        path = url.split(sandbox_check.ODATA_PATH, 1)[1]
        return FakeResponse({"d": {"results": bodies[path]}})

    def refuse(*args, **kwargs):
        raise AssertionError("the sandbox check must only send GET requests")

    monkeypatch.setattr(sandbox_check.requests, "get", fake_get)
    for method in ["post", "put", "patch", "delete", "request"]:
        monkeypatch.setattr(requests, method, refuse)

    reader = SapReader("https://sap.example.test", "test-key")
    result = sandbox_check.check_plant(reader, "AUC1", date(2026, 11, 7))

    assert len(sent) == 3
    assert result["statuses"]["orders"] == {"red": 1}
    assert result["description_example"] == ("M1", "One")
