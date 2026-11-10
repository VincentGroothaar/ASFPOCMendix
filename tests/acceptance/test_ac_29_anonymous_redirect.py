"""AC-29 (REQ-7 / INV-9): every URL redirects an anonymous user to login. Checked over every
URL in spec.md "Pages and URLs" and over every URL name the cockpit app defines."""

import pytest
from django.test import Client
from django.urls import URLPattern, URLResolver, get_resolver, reverse

from tests.acceptance.support import is_login_redirect

pytestmark = pytest.mark.xfail(strict=True, reason="Not built yet: #22")

SPEC_URLS = [
    "/",
    "/orders/",
    "/plants/AUC1/refresh/",
    "/orders/1000001/",
    "/orders/1000001/requisitions/?material=RM-1",
    "/requisitions/",
    "/requisitions/1/",
    "/requisitions/1/approve/",
    "/requisitions/1/reject/",
    "/dashboard/",
    "/settings/",
]


def cockpit_url_paths() -> list[str]:
    """One concrete path per named URL of the cockpit app, with sample arguments."""
    samples = {"int": 1, "str": "1000001", "slug": "x", "path": "x"}
    paths = []
    for entry in get_resolver().url_patterns:
        if not (isinstance(entry, URLResolver) and entry.namespace == "cockpit"):
            continue
        for pattern in entry.url_patterns:
            if isinstance(pattern, URLPattern) and pattern.name:
                converters = pattern.pattern.converters
                kwargs = {
                    name: samples.get(type(conv).__name__.removesuffix("Converter").lower(), "x")
                    for name, conv in converters.items()
                }
                paths.append(reverse(f"cockpit:{pattern.name}", kwargs=kwargs))
    return paths


@pytest.mark.parametrize("method", ["get", "post"])
def test_ac_29_every_url_sends_anonymous_users_to_login(method):
    client = Client()
    paths = SPEC_URLS + cockpit_url_paths()

    not_redirected = [
        (path, client_response.status_code)
        for path in paths
        if not is_login_redirect(client_response := getattr(client, method)(path))
    ]

    assert not_redirected == []
