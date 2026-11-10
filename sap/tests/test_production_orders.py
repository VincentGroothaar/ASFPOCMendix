"""Tests for reading released open production orders and their components."""

from datetime import date
from decimal import Decimal

import pytest

from sap.client import SapDataError
from sap.production_orders import (
    RELEASED_OPEN_FILTER,
    Component,
    ProductionOrder,
    read_released_orders,
)
from sap.tests.fake_http import FakeSap, client_for

NOV_4 = "/Date(1793750400000)/"  # 2026-11-04
NOV_5 = "/Date(1793836800000)/"  # 2026-11-05


def order_row(number: str = "1000001", **changes) -> dict:
    """An order row as SAP returns it: released, open, plant AUC1, two components."""
    row = {
        "ManufacturingOrder": number,
        "ProductionPlant": "AUC1",
        "Material": "FG-100",
        "TotalQuantity": "10",
        "ProductionUnit": "PC",
        "MfgOrderScheduledStartDate": NOV_4,
        "MfgOrderPlannedStartDate": NOV_5,
        "OrderIsReleased": "X",
        "OrderIsDelivered": "",
        "OrderIsTechnicallyCompleted": "",
        "OrderIsClosed": "",
        "OrderIsDeleted": "",
        "OrderIsMarkedForDeletion": "",
        "to_ProductionOrderComponent": {
            "results": [
                component_row("0002", "RM-B", "5.5", "0", "KG"),
                component_row("0001", "RM-A", "100", "40"),
            ]
        },
    }
    row.update(changes)
    return row


def component_row(item: str, material: str, required: str, withdrawn: str, unit="PC") -> dict:
    return {
        "ReservationItem": item,
        "Material": material,
        "RequiredQuantity": required,
        "WithdrawnQuantity": withdrawn,
        "BaseUnit": unit,
    }


def test_reads_orders_with_components_as_dataclasses() -> None:
    sap = FakeSap(rows={"A_ProductionOrder_2": [order_row()]})

    [order] = read_released_orders(client_for(sap), "AUC1")

    assert order == ProductionOrder(
        number="1000001",
        plant="AUC1",
        material="FG-100",
        quantity=Decimal("10"),
        unit="PC",
        start_date=date(2026, 11, 4),
        components=(
            Component("0001", "RM-A", Decimal("100"), Decimal("40"), "PC"),
            Component("0002", "RM-B", Decimal("5.5"), Decimal("0"), "KG"),
        ),
    )


def test_asks_sap_for_released_open_orders_of_the_plant_in_one_call() -> None:
    sap = FakeSap(rows={"A_ProductionOrder_2": [order_row()]})

    read_released_orders(client_for(sap), "AUC1")

    [call] = sap.calls
    assert call.path.endswith("/API_PRODUCTION_ORDER_2_SRV/A_ProductionOrder_2")
    assert call.param("$filter") == f"ProductionPlant eq 'AUC1' and {RELEASED_OPEN_FILTER}"
    assert call.param("$expand") == "to_ProductionOrderComponent"
    assert call.param("$orderby") == "ManufacturingOrder"
    select = call.param("$select").split(",")
    assert "MfgOrderScheduledStartDate" in select
    assert "to_ProductionOrderComponent/WithdrawnQuantity" in select


@pytest.mark.parametrize(
    "flag",
    [
        "OrderIsDelivered",
        "OrderIsTechnicallyCompleted",
        "OrderIsClosed",
        "OrderIsDeleted",
        "OrderIsMarkedForDeletion",
    ],
)
def test_orders_with_a_closing_flag_are_not_read(flag: str) -> None:
    sap = FakeSap(rows={"A_ProductionOrder_2": [order_row("1"), order_row("2", **{flag: "X"})]})

    orders = read_released_orders(client_for(sap), "AUC1")

    assert [order.number for order in orders] == ["1"]


def test_unreleased_orders_and_other_plants_are_not_read() -> None:
    rows = [
        order_row("1"),
        order_row("2", OrderIsReleased=""),
        order_row("3", ProductionPlant="USC1"),
    ]
    sap = FakeSap(rows={"A_ProductionOrder_2": rows})

    orders = read_released_orders(client_for(sap), "AUC1")

    assert [order.number for order in orders] == ["1"]


def test_start_date_is_the_scheduled_start() -> None:
    sap = FakeSap(rows={"A_ProductionOrder_2": [order_row()]})

    [order] = read_released_orders(client_for(sap), "AUC1")

    assert order.start_date == date(2026, 11, 4)  # scheduled, not the planned 5 Nov


def test_start_date_falls_back_to_the_basic_start_when_scheduled_is_empty() -> None:
    sap = FakeSap(rows={"A_ProductionOrder_2": [order_row(MfgOrderScheduledStartDate=None)]})

    [order] = read_released_orders(client_for(sap), "AUC1")

    assert order.start_date == date(2026, 11, 5)


def test_order_without_any_start_date_raises_sap_data_error() -> None:
    row = order_row(MfgOrderScheduledStartDate=None, MfgOrderPlannedStartDate=None)
    sap = FakeSap(rows={"A_ProductionOrder_2": [row]})

    with pytest.raises(SapDataError, match="1000001 has no start date"):
        read_released_orders(client_for(sap), "AUC1")


def test_order_without_components_has_an_empty_tuple() -> None:
    row = order_row(to_ProductionOrderComponent={"results": []})
    sap = FakeSap(rows={"A_ProductionOrder_2": [row]})

    [order] = read_released_orders(client_for(sap), "AUC1")

    assert order.components == ()


def test_missing_field_raises_sap_data_error() -> None:
    row = order_row()
    del row["TotalQuantity"]
    sap = FakeSap(rows={"A_ProductionOrder_2": [row]})

    with pytest.raises(SapDataError, match="TotalQuantity"):
        read_released_orders(client_for(sap), "AUC1")


def test_all_pages_are_read() -> None:
    rows = [order_row(str(1000000 + n)) for n in range(5)]
    sap = FakeSap(rows={"A_ProductionOrder_2": rows})

    orders = read_released_orders(client_for(sap, page_size=2), "AUC1")

    assert len(orders) == 5
    assert len(sap.calls) == 3


# --- Review round 1: item order and unusable rows ----------------------------------------------


def test_components_are_sorted_by_item_number_as_a_number() -> None:
    # The sandbox sends unpadded item numbers; as text "10" would come before "2".
    lines = [component_row(item, "RM-A", "1", "0") for item in ["2", "10", "1"]]
    row = order_row(to_ProductionOrderComponent={"results": lines})
    sap = FakeSap(rows={"A_ProductionOrder_2": [row]})

    [order] = read_released_orders(client_for(sap), "AUC1")

    assert [line.item for line in order.components] == ["1", "2", "10"]


def test_component_item_that_is_not_a_number_raises_sap_data_error() -> None:
    lines = [component_row("A1", "RM-A", "1", "0")]
    sap = FakeSap(
        rows={"A_ProductionOrder_2": [order_row(to_ProductionOrderComponent={"results": lines})]}
    )

    with pytest.raises(SapDataError, match="'A1'"):
        read_released_orders(client_for(sap), "AUC1")


@pytest.mark.parametrize(
    "components",
    [None, {"results": None}, {"results": [None]}, "text"],
)
def test_unusable_component_list_raises_sap_data_error(components: object) -> None:
    sap = FakeSap(rows={"A_ProductionOrder_2": [order_row(to_ProductionOrderComponent=components)]})

    with pytest.raises(SapDataError):
        read_released_orders(client_for(sap), "AUC1")


def test_missing_component_list_raises_sap_data_error() -> None:
    row = order_row()
    del row["to_ProductionOrderComponent"]
    sap = FakeSap(rows={"A_ProductionOrder_2": [row]})

    with pytest.raises(SapDataError, match="component list"):
        read_released_orders(client_for(sap), "AUC1")


@pytest.mark.parametrize(
    "field", ["ManufacturingOrder", "ProductionPlant", "Material", "ProductionUnit"]
)
def test_empty_order_field_raises_sap_data_error(field: str) -> None:
    # apply_filter=False: a row without a plant would not pass the fake's plant filter.
    sap = FakeSap(rows={"A_ProductionOrder_2": [order_row(**{field: None})]}, apply_filter=False)

    with pytest.raises(SapDataError, match=field):
        read_released_orders(client_for(sap), "AUC1")


def test_null_item_number_raises_sap_data_error() -> None:
    lines = [component_row("1", "RM-A", "1", "0"), component_row(None, "RM-B", "1", "0")]
    sap = FakeSap(
        rows={"A_ProductionOrder_2": [order_row(to_ProductionOrderComponent={"results": lines})]}
    )

    with pytest.raises(SapDataError, match="ReservationItem"):
        read_released_orders(client_for(sap), "AUC1")


def test_empty_plant_is_refused_before_calling_sap() -> None:
    sap = FakeSap(rows={"A_ProductionOrder_2": [order_row()]})

    with pytest.raises(ValueError):
        read_released_orders(client_for(sap), "")
    assert sap.calls == []
