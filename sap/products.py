"""Material descriptions (API_PRODUCT_SRV).

Field names come from the sandbox data check, docs/sandbox/findings.md (#7).
"""

from sap.client import ODataClient, SapDataError, any_of, batches, parse_text

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
            # SAP already filtered these rows; checking again keeps the rule visible here.
            product = parse_text(row, "Product")
            if row.get("Language") == LANGUAGE and product in batch:
                description = row.get("ProductDescription")
                if not isinstance(description, str):
                    raise SapDataError(f"SAP sent no description text for {product}.")
                descriptions[product] = description
    return descriptions
