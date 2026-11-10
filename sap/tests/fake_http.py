"""A fake HTTP layer for the SAP client tests: no network, every request recorded.

`FakeSap` is mounted on a real `requests.Session`, so the client builds its URLs and query
strings exactly as it would against the sandbox. It answers like SAP's OData V2 JSON and applies
$filter, $top and $skip to the rows it holds.
"""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse

import requests
from requests.adapters import BaseAdapter

from sap.client import ODataClient

BASE_URL = "https://sap.test"
API_KEY = "test-key"


@dataclass
class Call:
    """One request the client sent."""

    method: str
    url: str
    headers: dict[str, str]
    timeout: object

    @property
    def path(self) -> str:
        return urlparse(self.url).path

    def param(self, name: str) -> str | None:
        values = parse_qs(urlparse(self.url).query).get(name)
        return values[0] if values else None


def filter_matches(odata_filter: str | None, row: dict) -> bool:
    """Apply a filter of `Field eq 'value'` terms: `and` across fields, `or` within one field."""
    wanted: dict[str, set[str]] = {}
    for name, value in re.findall(r"(\w+) eq '([^']*)'", odata_filter or ""):
        wanted.setdefault(name, set()).add(value)
    return all(row.get(name) in values for name, values in wanted.items())


@dataclass
class FakeSap(BaseAdapter):
    """Answers GET requests from `rows` (entity set name → rows) like the SAP sandbox."""

    rows: dict[str, list[dict]] = field(default_factory=dict)
    calls: list[Call] = field(default_factory=list)
    # Set to replace the normal answer, e.g. to return an error or raise a timeout.
    answer: Callable[[Call], requests.Response] | None = None
    # Set to imitate SAP's own paging: at most this many rows per answer, plus a __next link.
    server_page_size: int | None = None
    # Set to False to imitate a server that ignores $filter and sends every row.
    apply_filter: bool = True

    def __post_init__(self) -> None:
        super().__init__()

    def send(self, request, timeout=None, **kwargs) -> requests.Response:
        call = Call(request.method, request.url, dict(request.headers), timeout)
        self.calls.append(call)
        if self.answer:
            return self.answer(call)
        entity_set = call.path.rsplit("/", 1)[-1]
        if entity_set not in self.rows:
            return response(404, {"error": {"message": {"value": "Resource not found"}}})

        odata_filter = call.param("$filter") if self.apply_filter else None
        matching = [row for row in self.rows[entity_set] if filter_matches(odata_filter, row)]
        skip = int(call.param("$skip") or 0)
        top = int(call.param("$top") or len(matching))
        if self.server_page_size:
            top = min(top, self.server_page_size)
        page = matching[skip : skip + top]
        body: dict = {"results": page}
        if self.server_page_size and skip + top < len(matching):
            body["__next"] = f"{call.url}&$skiptoken={skip + top}"
        return response(200, {"d": body})

    def close(self) -> None:
        pass


def response(status: int, body: object | None = None, text: str | None = None) -> requests.Response:
    """A `requests` response as if a server had sent it."""
    result = requests.Response()
    result.status_code = status
    result.encoding = "utf-8"
    if text is not None:
        result._content = text.encode()
    else:
        result._content = json.dumps(body).encode() if body is not None else b""
    return result


def client_for(sap: FakeSap, page_size: int = 1000) -> ODataClient:
    """An ODataClient whose HTTP traffic goes to `sap` instead of the network."""
    session = requests.Session()
    session.mount("https://", sap)
    return ODataClient(BASE_URL, API_KEY, page_size=page_size, session=session)
