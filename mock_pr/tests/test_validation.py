"""Unit tests of the requisition checks against SAP's saved $metadata (no database)."""

import pytest

from mock_pr.metadata import HEADER_TYPE, ITEM_TYPE, load_metadata_xml, parse_entity_types
from mock_pr.validation import InvalidRequisition, validate_requisition

ENTITY_TYPES = parse_entity_types(load_metadata_xml())
HEADER = ENTITY_TYPES[HEADER_TYPE]
ITEM = ENTITY_TYPES[ITEM_TYPE]


def requisition(**item_changes) -> dict:
    item = {
        "Material": "MZ-RM-C990-01",
        "Plant": "AUC1",
        "RequestedQuantity": "10",
        "BaseUnit": "PC",
        "DeliveryDate": "/Date(1762646400000)/",
        "PurchasingGroup": "001",
    }
    item.update(item_changes)
    return {"PurchaseRequisitionType": "NB", "to_PurchaseReqnItem": [item]}


def check(body: object):
    return validate_requisition(body, HEADER, ITEM)


def test_metadata_gives_types_and_lengths() -> None:
    assert ITEM.properties["Plant"].max_length == 4
    quantity = ITEM.properties["RequestedQuantity"]
    assert (quantity.edm_type, quantity.precision, quantity.scale) == ("Edm.Decimal", 13, 3)
    assert "to_PurchaseReqnItem" in HEADER.navigation


def test_a_valid_requisition_passes() -> None:
    result = check(requisition())

    assert result.header == {"PurchaseRequisitionType": "NB"}
    assert result.items[0]["Material"] == "MZ-RM-C990-01"


def test_an_iso_date_is_returned_in_odata_form() -> None:
    result = check(requisition(DeliveryDate="2025-11-09T00:00:00"))

    assert result.items[0]["DeliveryDate"] == "/Date(1762646400000)/"


@pytest.mark.parametrize("quantity", ["10", "10.125", 10, "9999999999.999", "0000000000012.5"])
def test_accepted_quantities(quantity) -> None:
    check(requisition(RequestedQuantity=quantity))


@pytest.mark.parametrize(
    ("quantity", "expected"),
    [
        ("0", "greater than 0"),
        ("-1", "greater than 0"),
        ("1.2345", "at most 3 decimals"),
        ("10000000000", "at most 10 digits"),
        ("ten", "not a number"),
        ("NaN", "not a number"),
        (1.5, "number as text"),
        (True, "number as text"),
        ("1E+50", "not a number"),
        ("1e3", "not a number"),
        (" 12.5 ", "not a number"),
        ("12.", "not a number"),
    ],
)
def test_rejected_quantities(quantity, expected) -> None:
    with pytest.raises(InvalidRequisition, match=expected):
        check(requisition(RequestedQuantity=quantity))


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ([], "JSON object"),
        ({"PurchaseRequisitionType": "NB"}, "at least one item"),
        ({"PurchaseRequisitionType": "NB", "to_PurchaseReqnItem": []}, "at least one item"),
        (
            {"to_PurchaseReqnItem": requisition()["to_PurchaseReqnItem"]},
            "'PurchaseRequisitionType' is required",
        ),
        ({**requisition(), "PurchaseRequisitionType": ""}, "'PurchaseRequisitionType' is required"),
        ({**requisition(), "SourceDetermination": "yes"}, "true or false"),
        ({**requisition(), "PurchaseRequisition": None}, "must not be null"),
        (requisition(DeliveryDate="tomorrow"), "expected a date"),
        (requisition(DeliveryDate="/Date(99999999999999999999999)/"), "out of range"),
        ({**requisition(), "PurReqnDescription": 123}, "expected text"),
        (requisition(Material="AB\u0000C"), "not allowed"),
        (requisition(Material="\ud800"), "not allowed"),
        (requisition(to_PurchaseReqnItemText=[]), "does not support a deep insert"),
        (requisition(Material=None), "'Material' is required"),
    ],
)
def test_invalid_requisitions_are_rejected(body, expected) -> None:
    with pytest.raises(InvalidRequisition, match=expected):
        check(body)


def test_odata_metadata_block_is_ignored() -> None:
    body = requisition()
    body["__metadata"] = {"type": "API_PURCHASEREQ_PROCESS_SRV.A_PurchaseRequisitionHeaderType"}

    assert "__metadata" not in check(body).header


def test_at_most_9999_items() -> None:
    body = requisition()
    body["to_PurchaseReqnItem"] = body["to_PurchaseReqnItem"] * 10000

    with pytest.raises(InvalidRequisition, match="at most 9999 items"):
        check(body)
