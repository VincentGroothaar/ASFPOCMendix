"""Shared tools for the acceptance tests (issue #15).

Nothing in here knows how the app is built. It only uses what the spec fixes:

- **Fake SAP and fake mock.** They answer at the HTTP level (they replace the transport under
  `requests`), with the entity sets, fields and JSON shapes from spec.md "SAP reads" and
  mock_pr/README.md. The app code itself is never patched.
- **Test data.** `Order`, `Component` and `Stock` describe a plant in plain values.
- **Pages.** Small helpers that read text, table rows and buttons from rendered HTML.

Everything that depends on how the app is built (models, form fields) is in builders.py.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from html.parser import HTMLParser
from unittest import mock
from urllib.parse import parse_qs, unquote, urlparse

import requests
from django.test import override_settings
from requests.adapters import HTTPAdapter
from requests.structures import CaseInsensitiveDict

PLANT = "AUC1"
# The tests run on a fixed day: Tuesday 3 Nov 2026, 10:00 in Amsterdam (09:00 UTC).
NOW = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)
TODAY = date(2026, 11, 3)

SAP_URL = "https://sap.test"
SAP_KEY = "test-sap-key"
MOCK_URL = "https://mock.test"
MOCK_KEY = "test-mock-key"
MOCK_SERVICE = "/sap/opu/odata/sap/API_PURCHASEREQ_PROCESS_SRV"


def days(n: int) -> date:
    """The date n days after TODAY (negative for days before)."""
    return TODAY + timedelta(days=n)


# --- Test data ----------------------------------------------------------------------------------


@dataclass
class Component:
    """One component line of a production order, in the order's unit."""

    material: str
    required: Decimal
    unit: str = "PC"
    withdrawn: Decimal = Decimal("0")
    item: str = "0001"


@dataclass
class Order:
    """A production order as SAP returns it. The flags default to "released and open"."""

    number: str
    start: date
    components: list[Component] = field(default_factory=list)
    plant: str = PLANT
    material: str = "FG-100"
    quantity: Decimal = Decimal("10")
    unit: str = "PC"
    released: bool = True
    delivered: bool = False


@dataclass
class Stock:
    """Stock of one material in the plant, plus the change-request data from SAP."""

    material: str
    quantity: Decimal
    unit: str = "PC"
    plant: str = PLANT
    storage_location: str = "0001"
    stock_type: str = "01"  # 01 unrestricted, 02 quality inspection, 07 blocked
    special_stock: str = ""  # e.g. E (sales order), K (consignment)
    description: str = ""
    safety_stock: Decimal = Decimal("0")
    price: Decimal | None = None  # standard price for `price_unit` units of stock
    price_unit: Decimal = Decimal("1")
    currency: str = "EUR"


def one_component_order(
    number: str, start: date, material: str, required: str, unit: str = "PC"
) -> Order:
    """An order with a single component: the most common shape in these tests."""
    return Order(number, start, [Component(material, Decimal(required), unit)])


# --- Fake HTTP ----------------------------------------------------------------------------------


@dataclass
class SentRequest:
    """One HTTP request the app sent, as the fake saw it."""

    method: str
    url: str
    headers: dict[str, str]
    body: str

    @property
    def host(self) -> str:
        return urlparse(self.url).netloc

    @property
    def path(self) -> str:
        return unquote(urlparse(self.url).path)

    def query(self, name: str) -> str:
        values = parse_qs(urlparse(self.url).query).get(name, [""])
        return values[0]

    def json(self) -> dict:
        return json.loads(self.body)


def make_response(request, status: int, body: object = None, headers=None) -> requests.Response:
    """Build a `requests` response, as if a server had answered."""
    response = requests.Response()
    response.status_code = status
    response.url = request.url
    response.request = request
    response.encoding = "utf-8"
    response.headers = CaseInsensitiveDict(headers or {})
    if body is not None:
        response._content = json.dumps(body).encode()
        response.headers.setdefault("Content-Type", "application/json")
    else:
        response._content = b""
    return response


class FakeHttp:
    """Answers HTTP requests for the fake hosts; other hosts go to the real network."""

    def __init__(self) -> None:
        self.handlers: dict[str, Callable] = {}
        self.sent: list[SentRequest] = []
        self._real_send = HTTPAdapter.send

    def send(self, adapter, request, **kwargs):
        body = request.body or ""
        if isinstance(body, bytes):
            body = body.decode()
        sent = SentRequest(request.method, request.url, dict(request.headers), body)
        self.sent.append(sent)
        handler = self.handlers.get(sent.host)
        if handler is None:
            return self._real_send(adapter, request, **kwargs)
        return handler(request, sent)


@contextmanager
def fake_http() -> Iterator[FakeHttp]:
    """Route the app's `requests` traffic through a FakeHttp for the duration of the block."""
    fake = FakeHttp()

    def send(adapter, request, **kwargs):
        return fake.send(adapter, request, **kwargs)

    with mock.patch.object(HTTPAdapter, "send", send):
        yield fake


# --- Fake SAP -----------------------------------------------------------------------------------


def odata_date(value: date) -> str:
    """A date in OData V2 JSON form, e.g. /Date(1793750400000)/ (midnight UTC)."""
    moment = datetime(value.year, value.month, value.day, tzinfo=UTC)
    return f"/Date({int(moment.timestamp() * 1000)})/"


def parse_sap_date(value: str) -> date:
    """Read an OData V2 date (/Date(ms)/) or an ISO date as SAP and the mock accept them."""
    match = re.fullmatch(r"/Date\((\d+)\)/", value)
    if match:
        return datetime.fromtimestamp(int(match.group(1)) / 1000, tz=UTC).date()
    return date.fromisoformat(value[:10])


def filter_matches(odata_filter: str, row: dict) -> bool:
    """Apply a SAP-style $filter to one row, the way the sandbox would.

    The queries in spec.md only use `Field eq 'value'`, combined with `and` across fields and
    `or` within one field (a list of materials). So a row matches when, for every field the
    filter names and the row has, the row's value is one of the values named for it.
    """
    wanted: dict[str, set[str]] = {}
    for name, value in re.findall(r"(\w+) eq '([^']*)'", odata_filter):
        wanted.setdefault(name, set()).add(value)
    return all(row[name] in values for name, values in wanted.items() if name in row)


class FakeSap:
    """A fake SAP sandbox serving the read APIs in spec.md "SAP reads".

    Change `orders` and `stock` at any time; the next call sees the change. Set `failing` to make
    every call fail with a connection error.
    """

    def __init__(self, orders: list[Order] | None = None, stock: list[Stock] | None = None):
        self.orders: list[Order] = orders or []
        self.stock: list[Stock] = stock or []
        self.failing = False
        self.calls: list[SentRequest] = []

    # Rows per entity set, with SAP's field names. Decimals are strings, as in OData V2 JSON.

    def order_rows(self) -> list[dict]:
        flag = {True: "X", False: ""}
        return [
            {
                "ManufacturingOrder": order.number,
                "ProductionPlant": order.plant,
                "Material": order.material,
                "TotalQuantity": str(order.quantity),
                "ProductionUnit": order.unit,
                "MfgOrderScheduledStartDate": odata_date(order.start),
                "OrderIsReleased": flag[order.released],
                "OrderIsDelivered": flag[order.delivered],
                "OrderIsTechnicallyCompleted": "",
                "OrderIsClosed": "",
                "OrderIsDeleted": "",
                "OrderIsMarkedForDeletion": "",
                "to_ProductionOrderComponent": {
                    "results": [
                        {
                            "ManufacturingOrder": order.number,
                            "ReservationItem": line.item,
                            "Material": line.material,
                            "Plant": order.plant,
                            "RequiredQuantity": str(line.required),
                            "WithdrawnQuantity": str(line.withdrawn),
                            "BaseUnit": line.unit,
                        }
                        for line in order.components
                    ]
                },
            }
            for order in self.orders
        ]

    def stock_rows(self) -> list[dict]:
        return [
            {
                "Material": row.material,
                "Plant": row.plant,
                "StorageLocation": row.storage_location,
                "InventoryStockType": row.stock_type,
                "InventorySpecialStockType": row.special_stock,
                "MatlWrhsStkQtyInMatlBaseUnit": str(row.quantity),
                "MaterialBaseUnit": row.unit,
            }
            for row in self.stock
        ]

    def _first_per_material(self) -> list[Stock]:
        seen: dict[tuple[str, str], Stock] = {}
        for row in self.stock:
            seen.setdefault((row.material, row.plant), row)
        return list(seen.values())

    def description_rows(self) -> list[dict]:
        materials = {line.material for order in self.orders for line in order.components}
        materials |= {row.material for row in self.stock}
        given = {row.material: row.description for row in self.stock if row.description}
        return [
            {
                "Product": material,
                "Language": "EN",
                "ProductDescription": given.get(material, f"Description of {material}"),
            }
            for material in sorted(materials)
        ]

    def supply_planning_rows(self) -> list[dict]:
        return [
            {
                "Product": row.material,
                "Plant": row.plant,
                "SafetyStockQuantity": str(row.safety_stock),
            }
            for row in self._first_per_material()
        ]

    def valuation_rows(self) -> list[dict]:
        return [
            {
                "Product": row.material,
                "ValuationArea": row.plant,
                "StandardPrice": str(row.price),
                "PriceUnitQty": str(row.price_unit),
                "Currency": row.currency,
            }
            for row in self._first_per_material()
            if row.price is not None
        ]

    def entity_sets(self) -> dict[str, Callable[[], list[dict]]]:
        return {
            "A_ProductionOrder_2": self.order_rows,
            "A_MatlStkInAcctMod": self.stock_rows,
            "A_ProductDescription": self.description_rows,
            "A_ProductSupplyPlanning": self.supply_planning_rows,
            "A_ProductValuation": self.valuation_rows,
        }

    def answer(self, request, sent: SentRequest) -> requests.Response:
        """Answer one HTTP request like the SAP sandbox would."""
        self.calls.append(sent)
        if self.failing:
            raise requests.ConnectionError("Fake SAP is down")
        if sent.headers.get("APIKey") != SAP_KEY:
            return make_response(request, 401, {"fault": "Invalid ApiKey"})
        if sent.method != "GET":
            return make_response(request, 405, {"error": "The sandbox is read only"})
        for entity_set, rows in self.entity_sets().items():
            if sent.path.endswith("/" + entity_set):
                return make_response(request, 200, {"d": {"results": self._page(rows(), sent)}})
        return make_response(request, 404, {"error": f"Unknown path {sent.path}"})

    @staticmethod
    def _page(rows: list[dict], sent: SentRequest) -> list[dict]:
        rows = [row for row in rows if filter_matches(sent.query("$filter"), row)]
        skip = int(sent.query("$skip") or 0)
        top = sent.query("$top")
        return rows[skip : skip + int(top)] if top else rows[skip:]

    def calls_to(self, entity_set: str) -> list[SentRequest]:
        """The calls the app made to one entity set, e.g. "A_ProductionOrder_2"."""
        return [call for call in self.calls if call.path.endswith("/" + entity_set)]


# --- Fake requisition mock ----------------------------------------------------------------------


class FakeMock:
    """A fake of the purchase requisition mock (mock_pr), with its CSRF handshake.

    By default every POST succeeds with the next requisition number. Set `error` to a message to
    make POSTs fail with the mock's 400 error body instead.
    """

    TOKEN = "fake-csrf-token"

    def __init__(self) -> None:
        self.error: str | None = None
        self.next_number = 10000000
        self.calls: list[SentRequest] = []

    @property
    def posts(self) -> list[SentRequest]:
        return [call for call in self.calls if call.method == "POST"]

    def answer(self, request, sent: SentRequest) -> requests.Response:
        self.calls.append(sent)
        if sent.headers.get("APIKey") != MOCK_KEY:
            return make_response(request, 401, sap_error("UNAUTHORIZED", "API key missing"))
        if sent.method == "GET":
            headers = {}
            if sent.headers.get("X-CSRF-Token", "").lower() == "fetch":
                headers["X-CSRF-Token"] = self.TOKEN
            return make_response(request, 200, {"d": {"EntitySets": []}}, headers)
        if sent.headers.get("X-CSRF-Token") != self.TOKEN:
            return make_response(request, 403, None, {"X-CSRF-Token": "Required"})
        if self.error:
            return make_response(request, 400, sap_error("INVALID_REQUISITION", self.error))
        number = str(self.next_number)
        self.next_number += 1
        header = sent.json()
        items = header.get("to_PurchaseReqnItem", {})
        items = items.get("results", []) if isinstance(items, dict) else items
        for position, item in enumerate(items, start=1):
            item["PurchaseRequisition"] = number
            item["PurchaseRequisitionItem"] = str(position * 10)
        header["PurchaseRequisition"] = number
        header["to_PurchaseReqnItem"] = {"results": items}
        location = f"{MOCK_URL}{MOCK_SERVICE}/A_PurchaseRequisitionHeader('{number}')"
        return make_response(request, 201, {"d": header}, {"Location": location})


def sap_error(code: str, message: str) -> dict:
    """SAP's OData V2 error body, as the mock sends it."""
    return {"error": {"code": code, "message": {"lang": "en", "value": message}}}


def posted_item(post: SentRequest) -> dict:
    """The first (and only) item of a requisition the app posted."""
    items = post.json()["to_PurchaseReqnItem"]
    return (items["results"] if isinstance(items, dict) else items)[0]


@dataclass
class Fakes:
    """The fakes that are active in a test."""

    http: FakeHttp
    sap: FakeSap
    mock: FakeMock


@contextmanager
def fake_systems() -> Iterator[Fakes]:
    """Point the app at a fake SAP and a fake mock (INV-3: only through settings)."""
    with (
        fake_http() as http,
        override_settings(
            SAP_BASE_URL=SAP_URL,
            SAP_API_KEY=SAP_KEY,
            MOCK_PR_BASE_URL=MOCK_URL,
            MOCK_API_KEY=MOCK_KEY,
        ),
    ):
        sap = FakeSap()
        fake_mock = FakeMock()
        http.handlers[urlparse(SAP_URL).netloc] = sap.answer
        http.handlers[urlparse(MOCK_URL).netloc] = fake_mock.answer
        yield Fakes(http, sap, fake_mock)


# --- Reading pages ------------------------------------------------------------------------------


class _PageParser(HTMLParser):
    """Collects the text of the page, of each table row, and of each button or link."""

    CLICKABLE = {"button", "a"}

    def __init__(self) -> None:
        super().__init__()
        self.text: list[str] = []
        self.rows: list[list[str]] = []
        self.clickables: list[list[str]] = []
        self.inputs: list[dict[str, str]] = []
        self._open_rows: list[list[str]] = []
        self._open_clickables: list[list[str]] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        attributes = {name: value or "" for name, value in attrs}
        if tag in {"script", "style"}:
            self._skip += 1
        elif tag == "tr" or attributes.get("role") == "row":
            self._open_rows.append([])
        elif tag in self.CLICKABLE:
            self._open_clickables.append([])
        elif tag in {"input", "textarea", "select"}:
            self.inputs.append(attributes)

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self._skip = max(0, self._skip - 1)
        elif tag == "tr" and self._open_rows:
            self.rows.append(self._open_rows.pop())
        elif tag in self.CLICKABLE and self._open_clickables:
            self.clickables.append(self._open_clickables.pop())

    def handle_data(self, data):
        if self._skip:
            return
        for bucket in (self.text, *self._open_rows, *self._open_clickables):
            bucket.append(data)


def _squash(parts: list[str]) -> str:
    return " ".join(" ".join(parts).split())


@dataclass
class Page:
    """A rendered page, reduced to what a user reads."""

    text: str
    rows: list[str]
    clickables: list[str]
    inputs: list[dict[str, str]]

    def row_with(self, *needles: str) -> str:
        """The text of the one table row that contains all needles (fails if not exactly one)."""
        found = [row for row in self.rows if all(needle in row for needle in needles)]
        assert len(found) == 1, f"Expected one row with {needles}, found {len(found)}: {found}"
        return found[0]

    def has_row_with(self, *needles: str) -> bool:
        return any(all(needle in row for needle in needles) for row in self.rows)

    def has_button(self, label: str) -> bool:
        """True when a button or link has exactly this label."""
        return label in self.clickables

    def input_decimals(self) -> list[Decimal]:
        """The values of all form fields that hold a number."""
        values = []
        for field_attributes in self.inputs:
            try:
                values.append(Decimal(field_attributes.get("value", "").replace(",", "")))
            except ArithmeticError:
                continue
        return values


def read_page(response) -> Page:
    """Parse a Django test response (or HTML string) into a Page."""
    html = response if isinstance(response, str) else response.content.decode()
    parser = _PageParser()
    parser.feed(html)
    return Page(
        text=_squash(parser.text),
        rows=[_squash(row) for row in parser.rows],
        clickables=[_squash(item) for item in parser.clickables],
        inputs=parser.inputs,
    )


def quantity_texts(value: Decimal, unit: str) -> list[str]:
    """The ways ui-spec section 6 allows a quantity to be written, e.g. `1,500 PC`, `1.500 KG`.

    Up to 3 decimals; trailing zeros only where the source has them, so both `20 PC` and
    `20.000 PC` are accepted.
    """
    plain = value.normalize()
    decimals = max(0, -plain.as_tuple().exponent)
    texts = []
    for places in range(decimals, 4):
        number = f"{plain:,.{places}f}"
        texts += [f"{number} {unit}", f"{number.replace(',', '')} {unit}"]
    return texts


def shows_quantity(text: str, value: Decimal, unit: str) -> bool:
    """True when the text shows this quantity with its unit, in any allowed format."""
    return any(
        re.search(r"(?<![\d.,])" + re.escape(option) + r"(?!\w)", text)
        for option in quantity_texts(value, unit)
    )


def is_login_redirect(response) -> bool:
    """True when the response sends an anonymous user to the login page."""
    return response.status_code == 302 and response["Location"].startswith("/accounts/login/")


# --- Scenarios ----------------------------------------------------------------------------------


def sync(plant: str = PLANT) -> None:
    """Run a full sync of the plant against whatever SAP is active (spec.md: sync_plant)."""
    from cockpit.services.sync import sync_plant

    sync_plant(plant)


MIXED_ORDER = "1000001"


def load_mixed_order(sap: FakeSap, start_in_days: int = 1) -> None:
    """One order with a Short, a Low cover and a Covered component (buffer 10).

    RM-SHORT: needs 100, stock 70 (shortage 30). RM-LOW: needs 100, stock 104 (to 110% = 6).
    RM-COVER: needs 100, stock 200.
    """
    sap.orders.append(
        Order(
            MIXED_ORDER,
            days(start_in_days),
            [
                Component("RM-SHORT", Decimal("100"), item="0001"),
                Component("RM-LOW", Decimal("100"), item="0002"),
                Component("RM-COVER", Decimal("100"), item="0003"),
            ],
        )
    )
    sap.stock += [
        Stock("RM-SHORT", Decimal("70")),
        Stock("RM-LOW", Decimal("104")),
        Stock("RM-COVER", Decimal("200")),
    ]


# --- Live SAP sandbox (read only, for the tests' own reference reads) ---------------------------

RELEASED_OPEN = (
    "OrderIsReleased eq 'X' and OrderIsDelivered eq '' and OrderIsTechnicallyCompleted eq '' "
    "and OrderIsClosed eq '' and OrderIsDeleted eq '' and OrderIsMarkedForDeletion eq ''"
)


def read_live_sap(path: str, params: dict[str, str]) -> list[dict]:
    """GET one entity set from the live sandbox, the way spec.md "SAP reads" describes it.

    Used by the tests to know what SAP holds, independent of the app. Only ever a GET.
    """
    import os

    base_url = os.environ.get("SAP_BASE_URL") or "https://sandbox.api.sap.com"
    response = requests.get(
        f"{base_url}/s4hanacloud/sap/opu/odata/sap/{path}",
        params={**params, "$format": "json"},
        headers={"APIKey": os.environ["SAP_API_KEY"], "Accept": "application/json"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["d"]["results"]


def live_released_orders(plant: str = PLANT, top: int | None = None) -> list[dict]:
    """Released open orders of the plant with their components, from the live sandbox."""
    params = {
        "$filter": f"ProductionPlant eq '{plant}' and {RELEASED_OPEN}",
        "$expand": "to_ProductionOrderComponent",
    }
    if top:
        params["$top"] = str(top)
    return read_live_sap("API_PRODUCTION_ORDER_2_SRV/A_ProductionOrder_2", params)


def above_limit_plant(sap: FakeSap) -> None:
    """Order 1000101 needs 100 PC of RM-1 with no stock; RM-1 costs 200 EUR per PC.

    Requesting 60 PC is worth 12,000 EUR (above the approval limit); 50 PC is exactly 10,000.
    """
    sap.orders.append(one_component_order("1000101", days(1), "RM-1", "100"))
    sap.stock.append(Stock("RM-1", Decimal("0"), price=Decimal("200")))


ABOVE_LIMIT_CREATE = "/orders/1000101/requisitions/?material=RM-1"
