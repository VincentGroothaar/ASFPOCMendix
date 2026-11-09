"""Read the property list of the requisition header and item from SAP's saved $metadata.

The file is the real `$metadata` of `API_PURCHASEREQ_PROCESS_SRV`, saved from the SAP
sandbox by the sandbox data check (#7). The mock serves it as is and validates every
request against it, so it accepts exactly the fields SAP accepts.
"""

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
METADATA_FILE = REPO_ROOT / "docs" / "sandbox" / "metadata" / "API_PURCHASEREQ_PROCESS_SRV.xml"

HEADER_TYPE = "A_PurchaseRequisitionHeaderType"
ITEM_TYPE = "A_PurchaseRequisitionItemType"

EDM = "{http://schemas.microsoft.com/ado/2008/09/edm}"


@dataclass(frozen=True)
class Property:
    """One field of an entity, as described in $metadata."""

    name: str
    edm_type: str  # e.g. "Edm.String", "Edm.Decimal", "Edm.DateTime"
    max_length: int | None = None  # strings only
    precision: int | None = None  # decimals: total number of digits
    scale: int | None = None  # decimals: digits after the decimal point
    nullable: bool = True


@dataclass(frozen=True)
class EntityType:
    """The fields and navigation properties of one entity type."""

    name: str
    properties: dict[str, Property]
    navigation: set[str]


def load_metadata_xml() -> str:
    """Return the saved $metadata document as text."""
    return METADATA_FILE.read_text(encoding="utf-8")


def parse_entity_types(xml_text: str) -> dict[str, EntityType]:
    """Parse every entity type in a $metadata document, keyed by entity type name."""
    root = ET.fromstring(xml_text)
    entity_types = {}
    for element in root.iter(f"{EDM}EntityType"):
        properties = {}
        for prop in element.iter(f"{EDM}Property"):
            properties[prop.get("Name")] = _parse_property(prop)
        navigation = {nav.get("Name") for nav in element.iter(f"{EDM}NavigationProperty")}
        name = element.get("Name")
        entity_types[name] = EntityType(name=name, properties=properties, navigation=navigation)
    return entity_types


def parse_entity_sets(xml_text: str) -> list[str]:
    """Return the names of all entity sets, for the service document."""
    root = ET.fromstring(xml_text)
    return [entity_set.get("Name") for entity_set in root.iter(f"{EDM}EntitySet")]


def _parse_property(prop: ET.Element) -> Property:
    """Turn one <Property> element into a Property."""
    return Property(
        name=prop.get("Name"),
        edm_type=prop.get("Type"),
        max_length=_optional_int(prop.get("MaxLength")),
        precision=_optional_int(prop.get("Precision")),
        scale=_optional_int(prop.get("Scale")),
        nullable=prop.get("Nullable") != "false",
    )


def _optional_int(value: str | None) -> int | None:
    return None if value is None else int(value)
