"""Tests for reading material descriptions."""

from sap.products import read_descriptions
from sap.tests.fake_http import FakeSap, client_for

ROWS = [
    {"Product": "RM-1", "Language": "EN", "ProductDescription": "BKC-990 Frame"},
    {"Product": "RM-1", "Language": "DE", "ProductDescription": "BKC-990 Rahmen"},
    {"Product": "RM-2", "Language": "EN", "ProductDescription": "Wheel"},
]


def test_reads_the_english_description_per_material() -> None:
    sap = FakeSap(rows={"A_ProductDescription": ROWS})

    descriptions = read_descriptions(client_for(sap), ["RM-1", "RM-2", "RM-NONE"])

    assert descriptions == {"RM-1": "BKC-990 Frame", "RM-2": "Wheel"}
    [call] = sap.calls
    assert call.path.endswith("/API_PRODUCT_SRV/A_ProductDescription")
    assert call.param("$filter") == (
        "Language eq 'EN' and (Product eq 'RM-1' or Product eq 'RM-2' or Product eq 'RM-NONE')"
    )


def test_reads_materials_in_batches_of_40() -> None:
    materials = [f"RM-{n:03}" for n in range(41)]
    sap = FakeSap(rows={"A_ProductDescription": []})

    read_descriptions(client_for(sap), materials)

    assert [call.param("$filter").count("Product eq") for call in sap.calls] == [40, 1]
