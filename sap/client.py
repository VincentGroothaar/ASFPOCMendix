"""Read-only client for the SAP OData V2 sandbox APIs.

In Mendix terms this is the consumed OData service: it builds the URL, sends the API key and
reads all pages of an entity set. It can only read. There is deliberately no method that sends
POST, PUT, PATCH, MERGE or DELETE (INV-4).
"""

import re
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

# Every API sits under this path below SAP_BASE_URL (spec.md, "SAP reads").
ODATA_PATH = "/s4hanacloud/sap/opu/odata/sap"

TIMEOUT_SECONDS = 10
PAGE_SIZE = 1000
# A safety limit: no read in the cockpit comes near this. Reaching it means SAP is not paging
# the way we expect, and reading on would never end.
MAX_ROWS = 100_000
# Materials per call when filtering by material (spec.md: batches of 40).
MATERIAL_BATCH_SIZE = 40


class SapUnavailable(Exception):
    """SAP could not be reached, timed out, or answered with an error.

    The message never contains the API key, so it is safe to show or store.
    """


class SapDataError(SapUnavailable):
    """SAP answered, but with data the cockpit cannot use (for example a missing date).

    It is a kind of SapUnavailable, so a sync treats it the same way: keep the old snapshot.
    """


class ODataClient:
    """GET requests to SAP OData V2 services, with the APIKey header and paging."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = TIMEOUT_SECONDS,
        page_size: int = PAGE_SIZE,
        session: requests.Session | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._page_size = page_size
        self._session = session or requests.Session()
        # The key lives only in the session headers, never in a local variable, so it cannot
        # show up in Django's debug error page (which lists the local variables of each frame).
        self._session.headers.update({"APIKey": api_key, "Accept": "application/json"})

    @classmethod
    def from_settings(cls) -> "ODataClient":
        """Build the client from SAP_BASE_URL and SAP_API_KEY, the only allowed source (INV-3)."""
        if not settings.SAP_BASE_URL or not settings.SAP_API_KEY:
            raise ImproperlyConfigured("Set SAP_BASE_URL and SAP_API_KEY to read from SAP.")
        return cls(settings.SAP_BASE_URL, settings.SAP_API_KEY)

    def get_all(
        self,
        service: str,
        entity_set: str,
        *,
        filter: str | None = None,
        expand: str | None = None,
        select: str | None = None,
        orderby: str | None = None,
    ) -> list[dict]:
        """Read every row of an entity set, page by page, and return them as dicts.

        Pages are requested with $top and $skip. A page with fewer rows than asked for is the
        last one, unless SAP adds a `__next` link (SAP's own paging), in which case the next
        page is read as well. Raises SapUnavailable when any call fails, and SapDataError when
        SAP sends the same page twice or more than MAX_ROWS rows (paging that would never end).
        """
        url = f"{self._base_url}{ODATA_PATH}/{service}/{entity_set}"
        params = {"$format": "json"}
        for name, value in [
            ("$filter", filter),
            ("$expand", expand),
            ("$select", select),
            ("$orderby", orderby),
        ]:
            if value:
                params[name] = value

        rows: list[dict] = []
        previous_page: list[dict] = []
        while True:
            page_params = {**params, "$top": str(self._page_size), "$skip": str(len(rows))}
            body = self._get_json(url, page_params)
            page = body.get("results")
            if not isinstance(page, list) or not all(isinstance(row, dict) for row in page):
                raise SapDataError(f"SAP answered {entity_set} without a list of results.")
            if page and page == previous_page:
                raise SapDataError(f"SAP sent the same page of {entity_set} twice.")
            rows += page
            previous_page = page
            if len(rows) > MAX_ROWS:
                raise SapDataError(f"SAP sent more than {MAX_ROWS} rows of {entity_set}.")
            is_last_page = len(page) < self._page_size and not body.get("__next")
            if is_last_page or not page:
                return rows

    def _get_json(self, url: str, params: dict[str, str]) -> dict:
        """One GET call; returns the `d` part of SAP's JSON answer."""
        try:
            response = self._session.get(url, params=params, timeout=self._timeout)
        except requests.Timeout:
            raise SapUnavailable(f"SAP did not answer within {self._timeout} s.") from None
        except requests.RequestException as error:
            raise SapUnavailable(f"SAP could not be reached ({type(error).__name__}).") from None

        if not response.ok:
            raise SapUnavailable(f"SAP answered with HTTP {response.status_code}.")
        try:
            body = response.json()["d"]
        except (ValueError, KeyError, TypeError):
            raise SapDataError("SAP answered with something that is not OData JSON.") from None
        if not isinstance(body, dict):
            raise SapDataError("SAP answered with something that is not OData JSON.")
        return body


# --- Helpers for the read functions ----------------------------------------------------------


def check_plant(plant: object) -> str:
    """Return the plant code, or raise ValueError when it is empty (a mistake in our own code)."""
    if not isinstance(plant, str) or not plant.strip():
        raise ValueError("A plant code such as 'AUC1' is needed to read from SAP.")
    return plant


def quote(value: str) -> str:
    """An OData string literal: 'value', with any ' inside doubled."""
    return "'" + value.replace("'", "''") + "'"


def any_of(field: str, values: list[str]) -> str:
    """A filter that matches any of the values, e.g. (Material eq 'A' or Material eq 'B')."""
    return "(" + " or ".join(f"{field} eq {quote(value)}" for value in values) + ")"


def batches(values: list[str], size: int = MATERIAL_BATCH_SIZE) -> Iterator[list[str]]:
    """Split a list into consecutive parts of at most `size` items."""
    for start in range(0, len(values), size):
        yield values[start : start + size]


_ODATA_DATE = re.compile(r"/Date\((-?\d+)([+-]\d{4})?\)/")


def parse_date(value: object) -> date | None:
    """Turn an OData V2 date such as "/Date(1496707200000)/" into a date; None when empty.

    SAP sends dates as milliseconds since 1970 at midnight UTC. A time zone offset such as
    "+0000" is ignored, because the number is already in UTC.
    """
    if value in (None, ""):
        return None
    match = _ODATA_DATE.fullmatch(str(value))
    if not match:
        raise SapDataError(f"SAP sent a date in an unknown format: {value!r}.")
    try:
        return datetime.fromtimestamp(int(match.group(1)) / 1000, tz=UTC).date()
    except (ValueError, OverflowError, OSError):
        raise SapDataError(f"SAP sent a date that is out of range: {value!r}.") from None


def parse_text(row: dict, field: str) -> str:
    """The value of a text field that must be filled, such as an order number or a unit."""
    value = row.get(field)
    if not isinstance(value, str) or not value:
        raise SapDataError(f"SAP left out field {field!r} or sent it empty.")
    return value


def parse_decimal(value: object, field: str) -> Decimal:
    """Turn an OData V2 decimal (sent as a string, e.g. "12.500") into a Decimal, never a float."""
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        number = None
    if number is None or not number.is_finite():
        raise SapDataError(f"SAP sent a value for {field} that is not a number.")
    return number
