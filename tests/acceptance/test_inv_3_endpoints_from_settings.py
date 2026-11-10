"""INV-3: the SAP connection and requisition endpoint come from environment variables only
(SAP_BASE_URL, SAP_API_KEY, MOCK_PR_BASE_URL, MOCK_API_KEY). Test with overridden settings,
plus a scan of the app code for hard-coded hosts."""

from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse

import pytest

from tests.acceptance import builders
from tests.acceptance.support import (
    MIXED_ORDER,
    MOCK_KEY,
    MOCK_URL,
    SAP_KEY,
    SAP_URL,
    load_mixed_order,
    sync,
)

APP_CODE = [Path("cockpit"), Path("sap"), Path("config")]
HARD_CODED = ["sandbox.api.sap.com", "localhost:8001", "onrender.com"]


@pytest.mark.xfail(strict=True, reason="Not built yet: #27")
def test_inv_3_app_uses_the_configured_urls_and_keys(fakes, clock, client_as):
    load_mixed_order(fakes.sap)
    for stock in fakes.sap.stock:
        stock.price = Decimal("1")
    sync()

    client_as("Planner").post(
        f"/orders/{MIXED_ORDER}/requisitions/?material=RM-SHORT", builders.requisition_form("30")
    )

    hosts = {urlparse(SAP_URL).netloc: SAP_KEY, urlparse(MOCK_URL).netloc: MOCK_KEY}
    assert {request.host for request in fakes.http.sent} == set(hosts)
    for request in fakes.http.sent:
        assert request.headers.get("APIKey") == hosts[request.host], request.url


@pytest.mark.xfail(strict=True, reason="Not built yet: #18")
def test_inv_3_no_hosts_hard_coded_in_app_code():
    found = []
    for folder in APP_CODE:
        for source in folder.rglob("*.py"):
            if "tests" in source.parts:
                continue
            text = source.read_text()
            found += [f"{source}: {host}" for host in HARD_CODED if host in text]

    assert found == []
    assert Path("sap/client.py").exists(), "The SAP client is not built yet"
