"""Checks of the acceptance-test tools themselves (tests/acceptance/support.py).

The acceptance tests stay red until the app is built, so a bug in the fake SAP, the fake mock
or the page helpers would hide behind that red. These tests prove the tools work today.
"""

from datetime import date
from decimal import Decimal

import requests

from tests.acceptance.support import (
    MOCK_KEY,
    MOCK_SERVICE,
    MOCK_URL,
    SAP_KEY,
    SAP_URL,
    FakeMock,
    Order,
    Stock,
    days,
    fake_systems,
    filter_matches,
    odata_date,
    one_component_order,
    parse_sap_date,
    posted_item,
    read_page,
    shows_quantity,
)

ODATA = f"{SAP_URL}/s4hanacloud/sap/opu/odata/sap"


def sap_get(entity_set: str, **params: str) -> requests.Response:
    return requests.get(f"{ODATA}/{entity_set}", params=params, headers={"APIKey": SAP_KEY})


def test_filter_matches_and_across_fields_or_within_one():
    row = {"Plant": "AUC1", "Material": "RM-1", "InventoryStockType": "01"}

    assert filter_matches("Plant eq 'AUC1' and (Material eq 'RM-1' or Material eq 'RM-2')", row)
    assert not filter_matches("Plant eq 'USC1' and Material eq 'RM-1'", row)
    assert not filter_matches("InventoryStockType eq '02'", row)
    assert filter_matches("", row)


def test_fake_sap_applies_filters_and_paging():
    with fake_systems() as fakes:
        fakes.sap.orders += [
            one_component_order("1000001", days(1), "RM-1", "5"),
            Order("1000002", days(1), released=False),
            one_component_order("1000003", days(2), "RM-2", "5"),
        ]
        fakes.sap.stock += [
            Stock("RM-1", Decimal("3")),
            Stock("RM-1", Decimal("9"), stock_type="07"),
        ]

        released = sap_get(
            "API_PRODUCTION_ORDER_2_SRV/A_ProductionOrder_2",
            **{"$filter": "ProductionPlant eq 'AUC1' and OrderIsReleased eq 'X'", "$top": "1"},
        ).json()["d"]["results"]
        second_page = sap_get(
            "API_PRODUCTION_ORDER_2_SRV/A_ProductionOrder_2",
            **{"$filter": "OrderIsReleased eq 'X'", "$top": "1", "$skip": "1"},
        ).json()["d"]["results"]
        stock = sap_get(
            "API_MATERIAL_STOCK_SRV/A_MatlStkInAcctMod",
            **{"$filter": "Material eq 'RM-1' and InventoryStockType eq '01'"},
        ).json()["d"]["results"]

    assert [order["ManufacturingOrder"] for order in released] == ["1000001"]
    assert [order["ManufacturingOrder"] for order in second_page] == ["1000003"]
    component = released[0]["to_ProductionOrderComponent"]["results"][0]
    assert component["RequiredQuantity"] == "5"
    assert [row["MatlWrhsStkQtyInMatlBaseUnit"] for row in stock] == ["3"]


def test_fake_sap_checks_the_key_refuses_writes_and_can_fail():
    with fake_systems() as fakes:
        no_key = requests.get(f"{ODATA}/API_PRODUCT_SRV/A_ProductDescription")
        write = requests.post(
            f"{ODATA}/API_PRODUCT_SRV/A_ProductDescription", headers={"APIKey": SAP_KEY}
        )
        fakes.sap.failing = True
        try:
            sap_get("API_PRODUCT_SRV/A_ProductDescription")
            failed = False
        except requests.ConnectionError:
            failed = True

    assert no_key.status_code == 401
    assert write.status_code == 405
    assert failed


def test_fake_mock_needs_csrf_and_returns_numbers_or_errors():
    service = f"{MOCK_URL}{MOCK_SERVICE}"
    body = {"PurchaseRequisitionType": "NB", "to_PurchaseReqnItem": [{"Material": "RM-1"}]}
    with fake_systems() as fakes:
        without_token = requests.post(
            f"{service}/A_PurchaseRequisitionHeader", json=body, headers={"APIKey": MOCK_KEY}
        )
        token = requests.get(
            service, headers={"APIKey": MOCK_KEY, "X-CSRF-Token": "Fetch"}
        ).headers["X-CSRF-Token"]
        headers = {"APIKey": MOCK_KEY, "X-CSRF-Token": token}
        created = requests.post(
            f"{service}/A_PurchaseRequisitionHeader", json=body, headers=headers
        )
        fakes.mock.error = "Property 'Plant' is required (item 1)."
        refused = requests.post(
            f"{service}/A_PurchaseRequisitionHeader", json=body, headers=headers
        )

    assert without_token.status_code == 403
    assert token == FakeMock.TOKEN
    assert created.status_code == 201
    assert created.json()["d"]["PurchaseRequisition"] == "10000000"
    assert refused.status_code == 400
    assert refused.json()["error"]["message"]["value"] == "Property 'Plant' is required (item 1)."
    assert posted_item(fakes.mock.posts[1])["Material"] == "RM-1"


def test_dates_round_trip():
    assert odata_date(date(2026, 11, 4)) == "/Date(1793750400000)/"
    assert parse_sap_date("/Date(1793750400000)/") == date(2026, 11, 4)
    assert parse_sap_date("2026-11-04T00:00:00") == date(2026, 11, 4)


def test_read_page_finds_rows_buttons_and_inputs():
    html = """
      <h1>Order 1000001</h1>
      <script>var hidden = "Short";</script>
      <table>
        <tr><td>RM-1</td><td>1,500 PC</td><td>Short</td><td><button>Request</button></td></tr>
        <tr><td>RM-2</td><td>8.000 KG</td><td>Covered</td><td>–</td></tr>
      </table>
      <input name="quantity" value="30.000"><input name="csrf" value="abc">
    """

    page = read_page(html)

    assert "Short" in page.row_with("RM-1")
    assert not page.has_row_with("RM-3")
    assert page.has_button("Request")
    assert not page.has_button("Retry")
    assert page.input_decimals() == [Decimal("30.000")]
    assert "hidden" not in page.text


def test_shows_quantity_accepts_the_allowed_formats_only():
    assert shows_quantity("Available 1,500 PC", Decimal("1500"), "PC")
    assert shows_quantity("Available 1500 PC", Decimal("1500"), "PC")
    assert shows_quantity("Sent 8.000 KG", Decimal("8"), "KG")
    assert shows_quantity("Shortage 0.5 KG", Decimal("0.5"), "KG")
    assert not shows_quantity("Shortage 10.5 KG", Decimal("0.5"), "KG")
    assert not shows_quantity("Available 1,500 PC", Decimal("500"), "PC")
    assert not shows_quantity("Available 6 PCS", Decimal("6"), "PC")
