"""Tests for the SAP OData read client: URLs, headers, paging and error mapping."""

import inspect
from datetime import date
from decimal import Decimal

import pytest
import requests
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from sap.client import (
    ODataClient,
    SapDataError,
    SapUnavailable,
    any_of,
    batches,
    parse_date,
    parse_decimal,
    quote,
)
from sap.tests.fake_http import API_KEY, FakeSap, client_for, response

ROWS = [{"Id": str(n)} for n in range(1, 8)]


def test_get_sends_the_api_key_and_asks_for_json() -> None:
    sap = FakeSap(rows={"A_Set": ROWS})

    client_for(sap).get_all("SOME_SRV", "A_Set")

    [call] = sap.calls
    assert call.method == "GET"
    assert call.headers["APIKey"] == API_KEY
    assert call.param("$format") == "json"
    assert call.url.startswith("https://sap.test/s4hanacloud/sap/opu/odata/sap/SOME_SRV/A_Set?")


def test_get_passes_filter_expand_select_and_orderby() -> None:
    sap = FakeSap(rows={"A_Set": ROWS})

    client_for(sap).get_all(
        "SOME_SRV", "A_Set", filter="Id eq '1'", expand="to_X", select="Id,to_X/Y", orderby="Id"
    )

    [call] = sap.calls
    assert call.param("$filter") == "Id eq '1'"
    assert call.param("$expand") == "to_X"
    assert call.param("$select") == "Id,to_X/Y"
    assert call.param("$orderby") == "Id"


def test_get_uses_a_10_second_timeout_per_call() -> None:
    sap = FakeSap(rows={"A_Set": ROWS})

    client_for(sap).get_all("SOME_SRV", "A_Set")

    assert sap.calls[0].timeout == 10


def test_paging_reads_pages_with_top_and_skip_until_a_short_page() -> None:
    sap = FakeSap(rows={"A_Set": ROWS})

    rows = client_for(sap, page_size=3).get_all("SOME_SRV", "A_Set")

    assert rows == ROWS
    assert [(c.param("$top"), c.param("$skip")) for c in sap.calls] == [
        ("3", "0"),
        ("3", "3"),
        ("3", "6"),
    ]


def test_paging_stops_after_an_empty_page_when_rows_fill_whole_pages() -> None:
    sap = FakeSap(rows={"A_Set": ROWS[:6]})

    rows = client_for(sap, page_size=3).get_all("SOME_SRV", "A_Set")

    assert rows == ROWS[:6]
    assert len(sap.calls) == 3  # 3 + 3 + an empty page that ends it


def test_paging_keeps_reading_when_sap_pages_on_its_own() -> None:
    # SAP returns only 2 rows per answer with a __next link, although 1000 were asked for.
    sap = FakeSap(rows={"A_Set": ROWS}, server_page_size=2)

    rows = client_for(sap).get_all("SOME_SRV", "A_Set")

    assert rows == ROWS
    assert [c.param("$skip") for c in sap.calls] == ["0", "2", "4", "6"]


def test_empty_entity_set_returns_no_rows_in_one_call() -> None:
    sap = FakeSap(rows={"A_Set": []})

    assert client_for(sap).get_all("SOME_SRV", "A_Set") == []
    assert len(sap.calls) == 1


@pytest.mark.parametrize("status", [400, 401, 403, 404, 500, 503])
def test_non_2xx_answer_raises_sap_unavailable(status: int) -> None:
    sap = FakeSap(answer=lambda call: response(status, {"fault": "no"}))

    with pytest.raises(SapUnavailable, match=f"HTTP {status}"):
        client_for(sap).get_all("SOME_SRV", "A_Set")


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (requests.ConnectTimeout(), "did not answer within 10 s"),
        (requests.ReadTimeout(), "did not answer within 10 s"),
        (requests.ConnectionError(), "could not be reached"),
        (requests.exceptions.SSLError(), "could not be reached"),
    ],
)
def test_network_errors_and_timeouts_raise_sap_unavailable(error: Exception, message: str) -> None:
    def fail(call):
        raise error

    with pytest.raises(SapUnavailable, match=message):
        client_for(FakeSap(answer=fail)).get_all("SOME_SRV", "A_Set")


@pytest.mark.parametrize(
    "answer",
    [
        response(200, text="<html>Maintenance</html>"),
        response(200, {"no_d": {}}),
        response(200, {"d": "text"}),
        response(200, {"d": {"no_results": []}}),
    ],
)
def test_answer_that_is_not_odata_json_raises_sap_data_error(answer: requests.Response) -> None:
    with pytest.raises(SapDataError):
        client_for(FakeSap(answer=lambda call: answer)).get_all("SOME_SRV", "A_Set")


def test_sap_data_error_is_a_kind_of_sap_unavailable() -> None:
    # A sync catches SapUnavailable and keeps the old snapshot; bad data must do the same.
    assert issubclass(SapDataError, SapUnavailable)


def test_error_messages_never_contain_the_api_key() -> None:
    def fail(call):
        raise requests.ConnectionError(f"failed with headers {call.headers}")

    with pytest.raises(SapUnavailable) as raised:
        client_for(FakeSap(answer=fail)).get_all("SOME_SRV", "A_Set")

    assert API_KEY not in str(raised.value)
    assert raised.value.__cause__ is None


def test_client_has_no_write_methods() -> None:
    # INV-4: the only public methods read.
    public = [name for name, _ in inspect.getmembers(ODataClient) if not name.startswith("_")]

    assert sorted(public) == ["from_settings", "get_all"]


@override_settings(SAP_BASE_URL="https://configured.test/", SAP_API_KEY="configured-key")
def test_from_settings_uses_sap_base_url_and_api_key() -> None:
    sap = FakeSap(rows={"A_Set": []})
    client = ODataClient.from_settings()
    client._session.mount("https://", sap)

    client.get_all("SOME_SRV", "A_Set")

    assert sap.calls[0].url.startswith("https://configured.test/s4hanacloud/")
    assert sap.calls[0].headers["APIKey"] == "configured-key"


@pytest.mark.parametrize(("url", "key"), [("", "key"), ("https://sap.test", "")])
def test_from_settings_refuses_missing_configuration(url: str, key: str) -> None:
    with override_settings(SAP_BASE_URL=url, SAP_API_KEY=key):
        with pytest.raises(ImproperlyConfigured):
            ODataClient.from_settings()


# --- Helpers -----------------------------------------------------------------------------------


def test_quote_doubles_single_quotes() -> None:
    assert quote("AUC1") == "'AUC1'"
    assert quote("O'BRIEN") == "'O''BRIEN'"


def test_any_of_joins_values_with_or() -> None:
    assert any_of("Material", ["A", "B"]) == "(Material eq 'A' or Material eq 'B')"


def test_batches_splits_into_parts_of_40() -> None:
    parts = list(batches([str(n) for n in range(85)]))

    assert [len(part) for part in parts] == [40, 40, 5]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("/Date(1496707200000)/", date(2017, 6, 6)),
        ("/Date(1496707200000+0000)/", date(2017, 6, 6)),
        ("/Date(1793750400000)/", date(2026, 11, 4)),
        ("", None),
        (None, None),
    ],
)
def test_parse_date_reads_odata_v2_dates(value: str | None, expected: date | None) -> None:
    assert parse_date(value) == expected


def test_parse_date_rejects_unknown_formats() -> None:
    with pytest.raises(SapDataError):
        parse_date("2026-11-04")


def test_parse_decimal_keeps_exact_decimals() -> None:
    assert parse_decimal("109.999", "Qty") == Decimal("109.999")
    assert isinstance(parse_decimal("1", "Qty"), Decimal)


@pytest.mark.parametrize("value", ["abc", "", None, "NaN", "Infinity"])
def test_parse_decimal_rejects_non_numbers(value: object) -> None:
    with pytest.raises(SapDataError, match="Qty"):
        parse_decimal(value, "Qty")
