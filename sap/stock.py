"""Unrestricted-use stock per material in a plant (API_MATERIAL_STOCK_SRV).

Field names and stock codes come from the sandbox data check, docs/sandbox/findings.md (#7).
"""

from dataclasses import dataclass
from decimal import Decimal

from sap.client import (
    ODataClient,
    SapDataError,
    any_of,
    batches,
    check_plant,
    parse_decimal,
    parse_text,
    quote,
)

SERVICE = "API_MATERIAL_STOCK_SRV"
ENTITY_SET = "A_MatlStkInAcctMod"

# Stock type 01 is unrestricted use (02 is quality inspection, 07 blocked). Special stock,
# such as E (sales order) or K (consignment), has a non-empty special stock type.
UNRESTRICTED = "01"
NO_SPECIAL_STOCK = ""
UNRESTRICTED_FILTER = (
    f"InventoryStockType eq '{UNRESTRICTED}' and InventorySpecialStockType eq '{NO_SPECIAL_STOCK}'"
)

FIELDS = [
    "Material",
    "Plant",
    "StorageLocation",
    "InventoryStockType",
    "InventorySpecialStockType",
    "MatlWrhsStkQtyInMatlBaseUnit",
    "MaterialBaseUnit",
]


@dataclass(frozen=True)
class MaterialStock:
    """Unrestricted-use stock of one material in a plant, summed over storage locations."""

    material: str
    quantity: Decimal
    unit: str


def read_unrestricted_stock(
    client: ODataClient, plant: str, materials: list[str]
) -> dict[str, MaterialStock]:
    """Read unrestricted-use, non-special stock of the materials in one plant (REQ-3).

    Quality inspection, blocked and special stock are left out. The quantity is summed over
    all storage locations. A material without stock rows is not in the result: the caller
    treats it as stock 0. Materials are read in batches of 40 per call.
    """
    check_plant(plant)
    totals: dict[str, MaterialStock] = {}
    for batch in batches(sorted(set(materials))):
        rows = client.get_all(
            SERVICE,
            ENTITY_SET,
            filter=f"Plant eq {quote(plant)} and {UNRESTRICTED_FILTER} and "
            f"{any_of('Material', batch)}",
            select=",".join(FIELDS),
        )
        for row in rows:
            # SAP already filtered these rows; checking again keeps the rule visible here and
            # guarantees that no other stock is ever counted (AC-12).
            if _counts_as_unrestricted(row, plant, batch):
                _add_row(totals, row)
    return totals


def _counts_as_unrestricted(row: dict, plant: str, materials: list[str]) -> bool:
    """True when a stock row is unrestricted, non-special stock of a wanted material and plant."""
    return (
        row.get("Plant") == plant
        and row.get("Material") in materials
        and row.get("InventoryStockType") == UNRESTRICTED
        and row.get("InventorySpecialStockType") == NO_SPECIAL_STOCK
    )


def _add_row(totals: dict[str, MaterialStock], row: dict) -> None:
    """Add one stock row (one storage location, batch, ...) to the material's total."""
    material = parse_text(row, "Material")
    unit = parse_text(row, "MaterialBaseUnit")
    quantity = parse_decimal(row.get("MatlWrhsStkQtyInMatlBaseUnit"), "stock quantity")

    current = totals.get(material)
    if current is None:
        totals[material] = MaterialStock(material, quantity, unit)
        return
    if current.unit != unit:
        # Stock is always kept in the material's base unit, so this should never happen.
        # Adding two units together would be wrong, so stop instead.
        raise SapDataError(f"SAP sent stock of {material} in both {current.unit} and {unit}.")
    totals[material] = MaterialStock(material, current.quantity + quantity, unit)
