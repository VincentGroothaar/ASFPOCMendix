"""AC-29 (REQ-7 / INV-9): every URL redirects an anonymous user to login. Checked over every
URL in spec.md "Pages and URLs" and over every URL name the cockpit app defines."""

import pytest
from django.test import Client
from django.urls import URLPattern, URLResolver, get_resolver, reverse
from django.urls.converters import IntConverter

from tests.acceptance.support import is_login_redirect

pytestmark = pytest.mark.xfail(strict=True, reason="Not built yet: #34")

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


def sample_value(converter) -> object:
    """A value that fits a URL argument: a number for <int:...>, otherwise a text."""
    return 1 if isinstance(converter, IntConverter) else "1000001"


def cockpit_url_paths() -> list[str]:
    """One concrete path per named URL of the cockpit app, so new URLs are checked too."""
    paths = []
    for entry in get_resolver().url_patterns:
        if not isinstance(entry, URLResolver) or entry.namespace != "cockpit":
            continue
        for pattern in entry.url_patterns:
            if not isinstance(pattern, URLPattern) or not pattern.name:
                continue
            arguments = {}
            for name, converter in pattern.pattern.converters.items():
                arguments[name] = sample_value(converter)
            paths.append(reverse(f"cockpit:{pattern.name}", kwargs=arguments))
    return paths


@pytest.mark.parametrize("method", ["get", "post"])
def test_ac_29_every_url_sends_anonymous_users_to_login(method):
    client = Client()
    send = client.get if method == "get" else client.post

    not_redirected = []
    for path in SPEC_URLS + cockpit_url_paths():
        response = send(path)
        if not is_login_redirect(response):
            not_redirected.append((path, response.status_code))

    assert not_redirected == []
