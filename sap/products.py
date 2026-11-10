"""Material descriptions (API_PRODUCT_SRV).

Field names come from the sandbox data check, docs/sandbox/findings.md (#7).
"""

from sap.client import ODataClient, SapDataError, any_of, batches

SERVICE = "API_PRODUCT_SRV"
DESCRIPTIONS = "A_ProductDescription"
LANGUAGE = "EN"


def read_descriptions(client: ODataClient, materials: list[str]) -> dict[str, str]:
    """Read the English description of each material (REQ-2), e.g. "BKC-990 Frame".

    A material without an English description is not in the result. Materials are read in
    batches of 40 per call.
    """
    descriptions: dict[str, str] = {}
    for batch in batches(sorted(set(materials))):
        rows = client.get_all(
            SERVICE,
            DESCRIPTIONS,
            filter=f"Language eq '{LANGUAGE}' and {any_of('Product', batch)}",
            select="Product,Language,ProductDescription",
        )
        for row in rows:
            try:
                if row["Language"] == LANGUAGE and row["Product"] in batch:
                    descriptions[row["Product"]] = row["ProductDescription"]
            except KeyError as missing:
                raise SapDataError(f"SAP left out field {missing} in a description.") from None
    return descriptions
