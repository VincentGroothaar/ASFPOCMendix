"""AC-20 (REQ-4): every status shows a tooltip with the rule; the Low cover and Covered texts
show the current buffer value. Browser test; texts word for word from ui-spec 5.2."""

import pytest

from tests.acceptance import builders
from tests.acceptance.support import MIXED_ORDER, load_mixed_order

TOOLTIPS = {
    "Short": (
        "Short: available stock is below the open requirement, after earlier orders take "
        "their share."
    ),
    "Low cover": (
        "Low cover: covered, but less than 10% to spare (available below 110% of required). "
        "Nothing is reserved."
    ),
    "Covered": "Covered: at least 10% to spare.",
}


def tooltip_shows(page, status: str, text: str, how: str) -> None:
    from playwright.sync_api import expect

    icon = page.get_by_role("button", name=f"What does {status} mean?").first
    expect(page.get_by_text(text, exact=True)).to_be_hidden()
    if how == "hover":
        icon.hover()
    else:
        icon.focus()
    expect(page.get_by_text(text, exact=True)).to_be_visible()
    page.mouse.move(0, 0)
    icon.blur()


@pytest.mark.xfail(strict=True, reason="Not built yet: #26")
@pytest.mark.parametrize("how", ["hover", "focus"])
def test_ac_20_browser_each_status_has_its_rule_tooltip(fakes, running_clock, browser_as, how):
    load_mixed_order(fakes.sap)

    page = browser_as(f"/orders/{MIXED_ORDER}/", role="Viewer")

    for status, text in TOOLTIPS.items():
        tooltip_shows(page, status, text, how)


@pytest.mark.xfail(strict=True, reason="Not built yet: #34")
def test_ac_20_browser_tooltips_show_the_current_buffer(fakes, running_clock, browser_as):
    load_mixed_order(fakes.sap)
    manager = builders.make_user("Manager")
    from django.test import Client

    client = Client()
    client.force_login(manager)
    client.post("/settings/", builders.buffer_form("12.5"))

    page = browser_as(f"/orders/{MIXED_ORDER}/", user=manager)

    tooltip_shows(page, "Covered", "Covered: at least 12.5% to spare.", "hover")
