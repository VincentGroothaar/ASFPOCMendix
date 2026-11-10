"""AC-8 (REQ-1): when the first sync of a plant fails, an error page says SAP is unavailable."""

import pytest

from tests.acceptance.support import PLANT, read_page

pytestmark = pytest.mark.xfail(strict=True, reason="Not built yet: #24")


def test_ac_8_first_sync_failure_shows_the_error_page(fakes, clock, client_as):
    fakes.sap.failing = True

    page = read_page(client_as("Viewer").get("/orders/"))

    # ui-spec 4.7, state D.
    assert f"No data for plant {PLANT} yet" in page.text
    assert page.has_button("Try again")
