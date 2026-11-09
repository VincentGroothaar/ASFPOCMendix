"""Sandbox data check (issue #7): what does the SAP sandbox actually return?

An investigation tool, not part of the app. The Cockpit must not import this
module, and it does not replace the SAP client in `sap/` that is built later.

Run from the repository root:

    uv run python -m scripts.sandbox_check

It needs only SAP_BASE_URL and SAP_API_KEY (from the environment or `.env`).
It sends GET requests only. It saves:

- the raw `$metadata` of the four APIs in docs/sandbox/metadata/
- the measured results in docs/sandbox/check_results.json

docs/sandbox/findings.md explains the results in words.
"""

import json
import os
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import requests

from config.env import load_env_file

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "docs" / "sandbox"
METADATA_DIR = OUTPUT_DIR / "metadata"

ODATA_PATH = "/s4hanacloud/sap/opu/odata/sap/"
PRODUCTION_ORDER_API = "API_PRODUCTION_ORDER_2_SRV"
STOCK_API = "API_MATERIAL_STOCK_SRV"
PRODUCT_API = "API_PRODUCT_SRV"
PURCHASE_REQUISITION_API = "API_PURCHASEREQ_PROCESS_SRV"
METADATA_APIS = [PRODUCTION_ORDER_API, STOCK_API, PRODUCT_API, PURCHASE_REQUISITION_API]

TIMEOUT_SECONDS = 60
# Materials per stock or description call; keeps the URL short.
MATERIALS_PER_CALL = 40

# Status flags on A_ProductionOrder_2. "X" means set, "" means not set.
STATUS_FLAGS = [
    "OrderIsReleased",
    "OrderIsPartiallyReleased",
    "OrderIsDelivered",
    "OrderIsTechnicallyCompleted",
    "OrderIsClosed",
    "OrderIsDeleted",
    "OrderIsMarkedForDeletion",
]

# Released, and not delivered, technically completed, closed, deleted or marked for deletion.
RELEASED_OPEN_FILTER = (
    "OrderIsReleased eq 'X'"
    " and OrderIsDelivered eq ''"
    " and OrderIsTechnicallyCompleted eq ''"
    " and OrderIsClosed eq ''"
    " and OrderIsDeleted eq ''"
    " and OrderIsMarkedForDeletion eq ''"
)

START_DATE_FIELDS = ["MfgOrderScheduledStartDate", "MfgOrderPlannedStartDate"]
# The start date the calculation below uses (see findings.md for why).
START_DATE_FIELD = "MfgOrderScheduledStartDate"

ORDER_FIELDS = [
    "ManufacturingOrder",
    "ManufacturingOrderCategory",
    "ManufacturingOrderType",
    "ProductionPlant",
    "Plant",
    "OrderIsPartiallyDelivered",
    "Material",
    "TotalQuantity",
    "ProductionUnit",
    *START_DATE_FIELDS,
]
COMPONENT_FIELDS = [
    "ManufacturingOrder",
    "ReservationItem",
    "Material",
    "Plant",
    "RequiredQuantity",
    "WithdrawnQuantity",
    "BaseUnit",
    "ReservationIsFinallyIssued",
    "MatlCompIsMarkedForDeletion",
    "MaterialComponentIsPhantomItem",
]

# Unrestricted-use stock that is not special stock (sales order, consignment, ...).
UNRESTRICTED_STOCK_TYPE = "01"
NO_SPECIAL_STOCK = ""

BUFFER = Decimal("1.1")

# "/Date(<milliseconds since 1970>)/", optionally with an offset such as "+0000".
ODATA_DATE = re.compile(r"/Date\((-?\d+)(?:[+-]\d{4})?\)/")

# Exact factors to a base unit per dimension (REQ-4), keyed by SAP unit code as the
# sandbox returns it. SAP writes tonne as "TO", not "T".
UNIT_FACTORS = {
    "G": ("mass", Decimal("0.001")),
    "KG": ("mass", Decimal("1")),
    "TO": ("mass", Decimal("1000")),
    "ML": ("volume", Decimal("0.001")),
    "L": ("volume", Decimal("1")),
    "M3": ("volume", Decimal("1000")),
    "MM": ("length", Decimal("0.001")),
    "CM": ("length", Decimal("0.01")),
    "M": ("length", Decimal("1")),
}


class UnitMismatch(Exception):
    """Raised when two units cannot be converted into each other."""


@dataclass
class SapReader:
    """Sends GET requests to the SAP sandbox and keeps a log of every call."""

    base_url: str
    api_key: str
    calls: list[dict] = field(default_factory=list)

    def get(self, path: str, params: dict | None = None, accept: str = "application/json"):
        """GET one OData path and return the response. Raises on a non-2xx status.

        This is the only method that talks to SAP, and it only reads.
        """
        url = self.base_url.rstrip("/") + ODATA_PATH + path
        headers = {"APIKey": self.api_key, "Accept": accept}
        started = time.perf_counter()
        response = requests.get(url, headers=headers, params=params, timeout=TIMEOUT_SECONDS)
        seconds = round(time.perf_counter() - started, 2)
        self.calls.append({"path": path, "status": response.status_code, "seconds": seconds})
        response.raise_for_status()
        return response

    def get_results(self, path: str, params: dict) -> list[dict]:
        """GET an entity set and return its rows, following `__next` links if SAP pages."""
        rows: list[dict] = []
        response = self.get(path, params)
        while True:
            body = response.json()["d"]
            rows.extend(body["results"])
            next_link = body.get("__next")
            if not next_link:
                return rows
            # A __next link is a full URL; strip the base so get() can rebuild it.
            response = self.get(next_link.split(ODATA_PATH, 1)[1])

    def count(self, path: str, odata_filter: str) -> int:
        """Return the number of rows in an entity set that match a `$filter`."""
        return int(self.get(path + "/$count", {"$filter": odata_filter}).text)


def parse_odata_date(value: str | None) -> date | None:
    """Turn an OData V2 date such as "/Date(1496707200000)/" into a date, or None if empty.

    A time zone offset such as "/Date(1496707200000+0000)/" is ignored: the number
    before it is already in UTC. Raises ValueError for anything else.
    """
    if not value or not value.strip():
        return None
    match = ODATA_DATE.fullmatch(value.strip())
    if not match:
        raise ValueError(f"not an OData V2 date: {value!r}")
    milliseconds = int(match.group(1))
    return datetime.fromtimestamp(milliseconds / 1000, UTC).date()


def convert(quantity: Decimal, from_unit: str, to_unit: str) -> Decimal:
    """Convert a quantity between units of the same dimension. Raises UnitMismatch otherwise."""
    if from_unit == to_unit:
        return quantity
    if from_unit not in UNIT_FACTORS or to_unit not in UNIT_FACTORS:
        raise UnitMismatch(f"{from_unit} -> {to_unit}")
    from_dimension, from_factor = UNIT_FACTORS[from_unit]
    to_dimension, to_factor = UNIT_FACTORS[to_unit]
    if from_dimension != to_dimension:
        raise UnitMismatch(f"{from_unit} -> {to_unit}")
    return quantity * from_factor / to_factor


def unrestricted_stock(stock_rows: list[dict]) -> dict[str, tuple[Decimal, str]]:
    """Sum unrestricted-use, non-special stock per material over all storage locations.

    Returns {material: (quantity, unit)}, in the unit of the material's first row.
    Raises UnitMismatch if a later row's unit cannot be converted into it.
    """
    totals: dict[str, tuple[Decimal, str]] = {}
    for row in stock_rows:
        if row["InventoryStockType"] != UNRESTRICTED_STOCK_TYPE:
            continue
        if row["InventorySpecialStockType"] != NO_SPECIAL_STOCK:
            continue
        material = row["Material"]
        quantity, unit = totals.get(material, (Decimal(0), row["MaterialBaseUnit"]))
        row_quantity = convert(
            Decimal(row["MatlWrhsStkQtyInMatlBaseUnit"]), row["MaterialBaseUnit"], unit
        )
        totals[material] = (quantity + row_quantity, unit)
    return totals


def component_status(available: Decimal, open_requirement: Decimal) -> str:
    """Return red, amber or green for one component (REQ-4, 10% buffer)."""
    if available < open_requirement:
        return "red"
    if available < BUFFER * open_requirement:
        return "amber"
    return "green"


def calculate_statuses(orders: list[dict], stock: dict[str, tuple[Decimal, str]]) -> dict:
    """Run the REQ-4 rule by hand: allocate stock by start date, then order number.

    `orders` are A_ProductionOrder_2 rows with expanded `to_ProductionOrderComponent`.
    Orders without a start date go last. Within one order, component lines take stock
    one after the other, so a second line of the same material sees what the first left.

    Returns counts of component and order statuses, the status of each order
    (`order_status`), and the materials needed by two or more orders (competing demand).
    """
    severity = {"green": 1, "amber": 2, "red": 3}
    balance = {material: quantity for material, (quantity, _) in stock.items()}

    def sort_key(order: dict) -> tuple:
        start = parse_odata_date(order[START_DATE_FIELD]) or date.max
        return (start, order["ManufacturingOrder"].zfill(12))

    component_counts: Counter = Counter()
    order_status: dict[str, str] = {}
    orders_per_material: dict[str, set[str]] = defaultdict(set)

    for order in sorted(orders, key=sort_key):
        worst = None
        has_mismatch = False
        for component in order["to_ProductionOrderComponent"]["results"]:
            material = component["Material"]
            open_requirement = Decimal(component["RequiredQuantity"]) - Decimal(
                component["WithdrawnQuantity"]
            )
            if open_requirement <= 0:
                component_counts["issued"] += 1
                continue
            orders_per_material[material].add(order["ManufacturingOrder"])

            # A material without a stock row has no stock, in the component's own unit.
            stock_unit = stock.get(material, (Decimal(0), component["BaseUnit"]))[1]
            try:
                needed = convert(open_requirement, component["BaseUnit"], stock_unit)
            except UnitMismatch:
                component_counts["unit mismatch"] += 1
                has_mismatch = True
                continue

            available = max(Decimal(0), balance.get(material, Decimal(0)))
            status = component_status(available, needed)
            component_counts[status] += 1
            if worst is None or severity[status] > severity[worst]:
                worst = status
            # Only the real requirement leaves stock; the buffer does not.
            balance[material] = balance.get(material, Decimal(0)) - needed

        if worst and has_mismatch:
            label = f"{worst} + unit mismatch"
        elif has_mismatch:
            label = "unit mismatch only"
        else:
            label = worst or "no open components"
        order_status[order["ManufacturingOrder"]] = label

    competing = sorted(m for m, numbers in orders_per_material.items() if len(numbers) > 1)
    return {
        "components": dict(component_counts),
        "orders": dict(Counter(order_status.values())),
        "order_status": order_status,
        "materials_with_open_requirement": len(orders_per_material),
        "competing_materials": len(competing),
        "competing_material_examples": competing[:10],
    }


def save_metadata(reader: SapReader) -> dict[str, int]:
    """Download `$metadata` of each API into docs/sandbox/metadata/. Returns sizes in bytes."""
    METADATA_DIR.mkdir(parents=True, exist_ok=True)
    sizes = {}
    for api in METADATA_APIS:
        response = reader.get(f"{api}/$metadata", accept="application/xml")
        (METADATA_DIR / f"{api}.xml").write_text(response.text, encoding="utf-8")
        sizes[api] = len(response.content)
    return sizes


def find_plants(reader: SapReader) -> list[str]:
    """List every production plant that has orders, by excluding known plants until none remain."""
    path = f"{PRODUCTION_ORDER_API}/A_ProductionOrder_2"
    plants: list[str] = []
    while True:
        odata_filter = " and ".join(f"ProductionPlant ne '{plant}'" for plant in plants)
        params = {"$select": "ProductionPlant", "$top": "1000"}
        if odata_filter:
            params["$filter"] = odata_filter
        rows = reader.get(path, params).json()["d"]["results"]
        if not rows:
            return plants
        plants.extend(sorted({row["ProductionPlant"] for row in rows}))


def count_statuses(reader: SapReader, plant: str) -> dict[str, int]:
    """Count a plant's orders in total, per status flag, and released-and-open."""
    path = f"{PRODUCTION_ORDER_API}/A_ProductionOrder_2"
    plant_filter = f"ProductionPlant eq '{plant}'"
    counts = {"total": reader.count(path, plant_filter)}
    for flag in STATUS_FLAGS:
        counts[flag] = reader.count(path, f"{plant_filter} and {flag} eq 'X'")
    counts["released_open"] = reader.count(path, f"{plant_filter} and {RELEASED_OPEN_FILTER}")
    return counts


def fetch_released_orders(reader: SapReader, plant: str) -> list[dict]:
    """Read a plant's released, open orders with their components, in one call."""
    select = ORDER_FIELDS + [f"to_ProductionOrderComponent/{name}" for name in COMPONENT_FIELDS]
    params = {
        "$filter": f"ProductionPlant eq '{plant}' and {RELEASED_OPEN_FILTER}",
        "$expand": "to_ProductionOrderComponent",
        "$select": ",".join(select),
    }
    return reader.get_results(f"{PRODUCTION_ORDER_API}/A_ProductionOrder_2", params)


def material_batches(materials: list[str]) -> list[list[str]]:
    """Split a list of materials into batches of MATERIALS_PER_CALL."""
    return [
        materials[start : start + MATERIALS_PER_CALL]
        for start in range(0, len(materials), MATERIALS_PER_CALL)
    ]


def fetch_stock(reader: SapReader, plant: str, materials: list[str]) -> list[dict]:
    """Read all stock rows (every stock type) of the given materials in a plant."""
    rows: list[dict] = []
    for batch in material_batches(materials):
        material_filter = " or ".join(f"Material eq '{m}'" for m in batch)
        params = {"$filter": f"Plant eq '{plant}' and ({material_filter})"}
        rows.extend(reader.get_results(f"{STOCK_API}/A_MatlStkInAcctMod", params))
    return rows


def fetch_descriptions(reader: SapReader, materials: list[str]) -> dict[str, str]:
    """Read the English description of each material. Returns {material: description}."""
    descriptions: dict[str, str] = {}
    for batch in material_batches(materials):
        product_filter = " or ".join(f"Product eq '{m}'" for m in batch)
        params = {"$filter": f"Language eq 'EN' and ({product_filter})"}
        for row in reader.get_results(f"{PRODUCT_API}/A_ProductDescription", params):
            descriptions[row["Product"]] = row["ProductDescription"]
    return descriptions


def start_date_summary(orders: list[dict], today: date) -> dict:
    """Describe how the start-date fields are filled and where the dates fall relative to today."""
    summary: dict = {}
    for name in START_DATE_FIELDS:
        dates = [parse_odata_date(order[name]) for order in orders]
        filled = sorted(d for d in dates if d)
        summary[name] = {
            "filled": len(filled),
            "empty": len(dates) - len(filled),
            "earliest": str(filled[0]) if filled else None,
            "latest": str(filled[-1]) if filled else None,
        }
    differing = sum(
        1 for order in orders if order[START_DATE_FIELDS[0]] != order[START_DATE_FIELDS[1]]
    )
    starts = [parse_odata_date(order[START_DATE_FIELD]) for order in orders]
    summary["orders_where_fields_differ"] = differing
    summary["start_today_or_later"] = sum(1 for d in starts if d and d >= today)
    summary["start_in_last_14_days"] = sum(1 for d in starts if d and 0 < (today - d).days <= 14)
    summary["per_year"] = dict(sorted(Counter(str(d.year) for d in starts if d).items()))
    return summary


def describe_orders(orders: list[dict]) -> dict:
    """Count order categories and types, and flags that the release filter lets through."""
    return {
        "categories": dict(Counter(order["ManufacturingOrderCategory"] for order in orders)),
        "types": dict(Counter(order["ManufacturingOrderType"] for order in orders)),
        "plant_differs_from_production_plant": sum(
            1 for order in orders if order["Plant"] != order["ProductionPlant"]
        ),
        "partially_delivered": sum(1 for order in orders if order["OrderIsPartiallyDelivered"]),
    }


def describe_components(orders: list[dict]) -> dict:
    """Count components, their units and the flags that affect the open requirement."""
    components = [c for order in orders for c in order["to_ProductionOrderComponent"]["results"]]
    repeated = []
    for order in orders:
        per_material = Counter(
            c["Material"] for c in order["to_ProductionOrderComponent"]["results"]
        )
        repeated.extend(count for count in per_material.values() if count > 1)
    return {
        "orders_with_a_material_on_several_lines": sum(
            1
            for order in orders
            if len({c["Material"] for c in order["to_ProductionOrderComponent"]["results"]})
            < len(order["to_ProductionOrderComponent"]["results"])
        ),
        "lines_of_repeated_materials": sum(repeated),
        "orders_with_components": sum(
            1 for order in orders if order["to_ProductionOrderComponent"]["results"]
        ),
        "components": len(components),
        "materials": len({c["Material"] for c in components}),
        "units": dict(Counter(c["BaseUnit"] for c in components)),
        "withdrawn_above_zero": sum(1 for c in components if Decimal(c["WithdrawnQuantity"]) > 0),
        "finally_issued": sum(1 for c in components if c["ReservationIsFinallyIssued"]),
        "marked_for_deletion": sum(1 for c in components if c["MatlCompIsMarkedForDeletion"]),
        "phantom_items": sum(1 for c in components if c["MaterialComponentIsPhantomItem"]),
    }


def describe_stock(rows: list[dict]) -> dict:
    """Count stock rows per stock type, special stock type and unit."""
    return {
        "rows": len(rows),
        "stock_types": dict(Counter(row["InventoryStockType"] for row in rows)),
        "special_stock_types": dict(Counter(row["InventorySpecialStockType"] for row in rows)),
        "units": dict(Counter(row["MaterialBaseUnit"] for row in rows)),
    }


def check_plant(reader: SapReader, plant: str, today: date) -> dict:
    """Load one plant the way the Cockpit's sync will, timed, and run the status rule."""
    calls_before = len(reader.calls)
    started = time.perf_counter()
    orders = fetch_released_orders(reader, plant)
    materials = sorted(
        {c["Material"] for order in orders for c in order["to_ProductionOrderComponent"]["results"]}
    )
    stock_rows = fetch_stock(reader, plant, materials)
    descriptions = fetch_descriptions(reader, materials)
    seconds = round(time.perf_counter() - started, 2)
    calls = reader.calls[calls_before:]

    stock = unrestricted_stock(stock_rows)
    statuses = calculate_statuses(orders, stock)
    # The status of every single order is too long for the results file; the counts are kept.
    del statuses["order_status"]
    return {
        "plant": plant,
        "load": {
            "seconds_total": seconds,
            "calls": len(calls),
            "seconds_per_call": [call["seconds"] for call in calls],
        },
        "released_open_orders": len(orders),
        "orders": describe_orders(orders),
        "start_dates": start_date_summary(orders, today),
        "components": describe_components(orders),
        "stock": describe_stock(stock_rows),
        "materials_without_unrestricted_stock": sorted(set(materials) - set(stock)),
        "materials_without_description": sorted(set(materials) - set(descriptions)),
        "description_example": next(iter(descriptions.items()), None),
        "statuses": statuses,
    }


def check_paging(reader: SapReader, plant: str) -> dict:
    """Find out whether SAP pages results on its own and whether $top and $skip work."""
    path = f"{PRODUCTION_ORDER_API}/A_ProductionOrder_2"
    plant_filter = f"ProductionPlant eq '{plant}'"
    body = reader.get(path, {"$filter": plant_filter, "$select": "ManufacturingOrder"}).json()["d"]
    skipped = reader.get(
        path,
        {
            "$filter": plant_filter,
            "$select": "ManufacturingOrder",
            "$orderby": "ManufacturingOrder",
            "$top": "5",
            "$skip": "5",
        },
    ).json()["d"]
    large = reader.get(
        path, {"$filter": plant_filter, "$select": "ManufacturingOrder", "$top": "20000"}
    ).json()["d"]
    return {
        "plant": plant,
        "rows_without_top": len(body["results"]),
        "server_sent_next_link": bool(body.get("__next")),
        "rows_with_top_5_skip_5": len(skipped["results"]),
        "rows_with_top_20000": len(large["results"]),
    }


def main() -> None:
    """Run every check, print a short report and save the results as JSON."""
    load_env_file(REPO_ROOT / ".env")
    base_url = os.environ.get("SAP_BASE_URL", "").strip()
    api_key = os.environ.get("SAP_API_KEY", "").strip()
    if not base_url or not api_key:
        raise SystemExit("Set SAP_BASE_URL and SAP_API_KEY in the environment or in .env.")

    reader = SapReader(base_url, api_key)
    today = date.today()

    print("Saving $metadata ...")
    metadata_sizes = save_metadata(reader)

    print("Counting orders per plant and status ...")
    plants = find_plants(reader)
    status_counts = {plant: count_statuses(reader, plant) for plant in plants}

    print("Loading every plant with released open orders ...")
    plant_checks = {
        plant: check_plant(reader, plant, today)
        for plant in plants
        if status_counts[plant]["released_open"] > 0
    }
    chosen = max(
        plant_checks,
        key=lambda plant: plant_checks[plant]["components"]["orders_with_components"],
    )

    print("Checking paging on the largest plant ...")
    largest = max(plants, key=lambda plant: status_counts[plant]["total"])
    paging = check_paging(reader, largest)

    results = {
        "run_on": str(today),
        "release_filter": RELEASED_OPEN_FILTER,
        "start_date_field": START_DATE_FIELD,
        "metadata_bytes": metadata_sizes,
        "plants": plants,
        "status_counts": status_counts,
        "chosen_plant": chosen,
        "plant_checks": plant_checks,
        "paging": paging,
        "total_calls": len(reader.calls),
        "call_log": reader.calls,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_file = OUTPUT_DIR / "check_results.json"
    output_file.write_text(json.dumps(results, indent=2, default=str) + "\n", encoding="utf-8")

    print()
    print(f"Plants: {', '.join(plants)}")
    for plant, check in plant_checks.items():
        print(
            f"  {plant}: {check['released_open_orders']} released open orders, "
            f"loaded in {check['load']['seconds_total']} s with {check['load']['calls']} calls, "
            f"orders {check['statuses']['orders']}"
        )
    print(f"Chosen plant: {chosen}")
    print(f"{len(reader.calls)} GET calls in total. Results: {output_file.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
