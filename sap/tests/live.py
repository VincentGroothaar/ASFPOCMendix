"""Helpers for tests that read the live SAP sandbox (issue #75).

The sandbox is an outside system. When it is down, a live test cannot say anything about our
code, so it is skipped with the reason in the test log instead of failing CI. Anything that can
be our fault still fails: an HTTP 4xx answer (bad key, wrong filter or URL), unusable data
(SapDataError) and every assertion.
"""

import re
from collections.abc import Iterator
from contextlib import contextmanager

import pytest

from sap.client import SapDataError, SapUnavailable

# The SapUnavailable messages that mean the sandbox itself is down (see sap/client.py).
OUTAGE = re.compile(r"answered with HTTP 5\d\d|could not be reached|did not answer within")


def is_outage(error: SapUnavailable) -> bool:
    """True when the error means SAP is down, not that our request or our parsing is wrong."""
    return not isinstance(error, SapDataError) and bool(OUTAGE.search(str(error)))


@contextmanager
def skip_if_sandbox_down() -> Iterator[None]:
    """Run the block; skip the test when the live SAP sandbox turns out to be down."""
    try:
        yield
    except SapUnavailable as error:
        if is_outage(error):
            pytest.skip(f"SAP sandbox unavailable (outside outage): {error}")
        raise
