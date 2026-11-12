"""Tests for the Orders page and Refresh (cockpit/views.py `order_list`, `refresh_plant`; #25).

The snapshot is written straight into the test database with a fresh `synced_at`, so
`ensure_fresh` never calls SAP. Where a sync would run, the SAP settings are empty: since #69
that is a failed sync that stores nothing and calls nobody.
"""

import json
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest import mock

import pytest
import time_machine
from pytest_django.asserts import assertContains, assertNotContains

from cockpit.models import BufferChange, PlantSnapshot
from cockpit.tests.test_order_list import make_order, make_stock

NOW = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)  # 10:00 in Amsterdam
HTMX = {"HTTP_HX_REQUEST": "true"}


@pytest.fixture(autouse=True)
def clock():
    with time_machine.travel(NOW, tick=False) as traveller:
        yield traveller


@pytest.fixture(autouse=True)
def no_sap(settings):
    """No SAP connection and two plants, so a sync never leaves the test."""
    settings.SAP_BASE_URL = ""
    settings.COCKPIT_PLANTS = ["AUC1", "USC1"]


def synced(plant: str = "AUC1", at: datetime = NOW, error: str = "") -> PlantSnapshot:
    """A stored snapshot, synced at `at`; with `error`, the latest attempt failed afterwards."""
    return PlantSnapshot.objects.create(
        plant=plant,
        synced_at=at,
        last_sync_error=error,
        last_sync_error_at=NOW if error else None,
    )


# --- Roles --------------------------------------------------------------------------------------


@pytest.mark.parametrize("groups", [("Admin",), (), ("Viewer", "Planner")])
def test_admin_and_users_without_a_role_are_refused(client_as, groups) -> None:
    client = client_as(*groups)

    assert client.get("/orders/").status_code == 403
    assert client.post("/plants/AUC1/refresh/").status_code == 403


@pytest.mark.parametrize("role", ["Viewer", "Planner", "Manager"])
def test_business_roles_see_the_page(client_as, role) -> None:
    synced()

    response = client_as(role).get("/orders/")

    assertContains(response, "<h1>Production orders</h1>", html=True)


# --- Full page or fragment (R-I1) ---------------------------------------------------------------


def test_a_normal_request_gets_the_full_page(client_as) -> None:
    synced()

    response = client_as("Viewer").get("/orders/")

    assertContains(response, '<nav class="sidebar"')
    assertContains(response, 'id="order-filters"')
    assertContains(response, 'id="orders-results"')
    assertNotContains(response, "hx-swap-oob")
    assert "HX-Request" in response["Vary"]


def test_an_htmx_request_gets_the_results_and_the_out_of_band_blocks(client_as) -> None:
    synced()

    response = client_as("Viewer").get("/orders/", **HTMX)
    html = response.content.decode()

    assert '<nav class="sidebar"' not in html
    assert 'id="order-filters"' not in html
    assert 'id="orders-results"' in html
    swapped = re.findall(r'id="([a-z-]+)" hx-swap-oob="true"', html)
    assert sorted(swapped) == ["filter-chips", "filter-reset", "page-data"]
    assert "HX-Request" in response["Vary"]


def test_a_history_restore_gets_the_full_page(client_as) -> None:
    synced()

    response = client_as("Viewer").get("/orders/", HTTP_HX_HISTORY_RESTORE_REQUEST="true", **HTMX)

    assertContains(response, '<nav class="sidebar"')
    assertNotContains(response, "hx-swap-oob")


def test_after_a_plant_change_the_header_belongs_to_the_new_plant(client_as) -> None:
    synced("AUC1", at=NOW - timedelta(minutes=2))
    synced("USC1", at=NOW - timedelta(minutes=1))

    response = client_as("Viewer").get("/orders/", {"plant": "USC1"}, **HTMX)
    page_data = re.search(
        r'<div class="page-data" id="page-data".*?</div>', response.content.decode(), re.S
    )

    assert "Data as of 03 Nov 09:59" in page_data.group(0)
    assert 'hx-post="/plants/USC1/refresh/"' in page_data.group(0)


def test_the_list_filters_live_in_the_results_and_survive_every_request(client_as) -> None:
    synced()

    html = client_as("Viewer").get("/orders/", {"status": "short"}, **HTMX).content.decode()

    hidden = re.search(r'<input type="hidden" name="status"[^>]*>', html).group(0)
    assert 'form="order-filters"' in hidden and 'value="short"' in hidden
    assert 'autocomplete="off"' in hidden
    select = re.search(r'<select name="requisition"[^>]*>', html).group(0)
    assert 'form="order-filters"' in select and 'autocomplete="off"' in select
    assert 'hx-sync="#order-filters:replace"' in select


def test_the_filter_form_turns_off_autocomplete(client_as) -> None:
    synced()

    html = client_as("Viewer").get("/orders/").content.decode()

    assert re.search(r'<form id="order-filters"[^>]*autocomplete="off"', html)


def test_there_is_one_htmx_config_with_the_history_settings_and_the_403_rule(client_as) -> None:
    synced()

    html = client_as("Viewer").get("/orders/").content.decode()
    configs = re.findall(r"<meta name=\"htmx-config\" content='([^']*)'>", html)

    assert len(configs) == 1
    config = json.loads(configs[0])
    assert config["historyCacheSize"] == 0
    assert config["refreshOnHistoryMiss"] is True
    assert config["responseHandling"][0]["code"] == "403"


# --- Filter bar ---------------------------------------------------------------------------------


def test_chips_and_reset_link(client_as) -> None:
    synced()

    response = client_as("Viewer").get(
        "/orders/", {"from": "2026-11-05", "to": "2026-11-20", "status": "short"}
    )

    assertContains(response, "2 filters active:")
    assertContains(response, '<span class="chip">Plant AUC1</span>', html=True)
    assertContains(response, '<span class="chip">Start 05 Nov – 20 Nov 2026</span>', html=True)
    # Reset to default: default plant and range, the tile filter kept (R-I5, R2-I1).
    assertContains(
        response,
        'href="/orders/?plant=AUC1&amp;from=2026-11-03&amp;to=2026-11-17&amp;status=short"',
    )


def test_clear_is_shown_only_with_a_list_filter(client_as) -> None:
    synced()
    client = client_as("Viewer")

    assertNotContains(client.get("/orders/"), ">Clear</a>")
    response = client.get("/orders/", {"requisition": "none"})
    assertContains(response, ">Clear</a>")
    assertContains(response, "All orders · requisition: None")


# --- Tiles --------------------------------------------------------------------------------------


def test_tile_tooltips_show_the_current_buffer(client_as, make_user) -> None:
    synced()
    BufferChange.objects.create(value=Decimal("12.50"), changed_by=make_user("Manager"))

    response = client_as("Viewer").get("/orders/")

    assertContains(response, "but at least one has less than 12.5% to spare.")
    assertContains(response, "All components have at least 12.5% to spare.")
    assertContains(response, 'aria-label="What does Short mean?"')
    assertNotContains(response, 'aria-label="What does All orders mean?"')


def test_a_pressed_tile_clears_its_filter_on_the_next_click(client_as) -> None:
    synced()

    html = client_as("Viewer").get("/orders/", {"status": "short"}).content.decode()

    short = re.search(r'<button type="submit"[^>]*aria-pressed="true"[^>]*>', html).group(0)
    assert 'value=""' in short
    assert html.count('aria-pressed="true"') == 1


# --- Rows ---------------------------------------------------------------------------------------


def test_a_row_shows_number_material_date_quantity_status_and_label(client_as) -> None:
    synced()
    make_order("1000101", NOW.date() - timedelta(days=2), needs="20")
    make_stock("RM-1", "5")

    response = client_as("Viewer").get("/orders/")

    assertContains(response, '<a class="cell-main" href="/orders/1000101/">1000101</a>', html=True)
    assertContains(response, "FG-1 · Bike")
    assertContains(response, "01 Nov 2026")
    assertContains(response, "Overdue")
    assertContains(response, "1 PC")
    assertContains(response, "Short")
    assertContains(response, 'aria-label="Open order 1000101"')


def test_an_empty_list_says_so(client_as) -> None:
    synced()

    response = client_as("Viewer").get("/orders/")

    assertContains(response, "No orders match these filters.")
    assertContains(response, "Showing 0 of 0 orders")


# --- Sync states (ui-spec 4.7 C and D) ----------------------------------------------------------


def test_state_c_banner_keeps_the_data(client_as) -> None:
    synced(at=NOW - timedelta(minutes=1), error="SAP answered with HTTP 500.")
    make_order("1000101", NOW.date())

    response = client_as("Viewer").get("/orders/")

    assertContains(response, "SAP could not be reached. Showing data as of 03 Nov 09:59.")
    assertContains(response, "1000101")
    assertContains(response, 'hx-indicator=".sync-indicator"')


def test_state_d_without_sap_config_is_a_page_not_an_error(client_as) -> None:
    response = client_as("Viewer").get("/orders/")

    assert response.status_code == 200
    assertContains(response, "No data for plant AUC1 yet")
    assertContains(response, "The SAP connection is not configured. · 03 Nov 10:00")
    assertContains(response, ">Try again</button>")
    assertContains(response, ">Choose another plant</button>")
    assertNotContains(response, "Data as of")
    assertContains(response, '<div class="page-data" id="page-data">')  # empty, but there
    assert not PlantSnapshot.objects.exists()


def test_state_d_offers_another_plant_only_when_there_is_one(client_as, settings) -> None:
    settings.COCKPIT_PLANTS = ["AUC1"]

    response = client_as("Viewer").get("/orders/")

    assertContains(response, "No data for plant AUC1 yet")
    assertNotContains(response, "Choose another plant")


# --- Refresh ------------------------------------------------------------------------------------


def test_refresh_with_htmx_syncs_and_asks_for_a_reload(client_as) -> None:
    with mock.patch("cockpit.views.sync_plant") as sync_plant:
        response = client_as("Viewer").post("/plants/USC1/refresh/", **HTMX)

    sync_plant.assert_called_once_with("USC1")
    assert response.status_code == 204
    assert response["HX-Refresh"] == "true"


def test_refresh_without_htmx_goes_back_to_the_list(client_as) -> None:
    with mock.patch("cockpit.views.sync_plant"):
        response = client_as("Viewer").post("/plants/USC1/refresh/")

    assert response.status_code == 302
    assert response["Location"] == "/orders/?plant=USC1"


@pytest.mark.parametrize("plant", ["1710", "auc1", "AUC1%20"])
def test_refresh_of_an_unknown_plant_is_404_and_calls_nobody(client_as, plant) -> None:
    with mock.patch("cockpit.views.sync_plant") as sync_plant:
        response = client_as("Viewer").post(f"/plants/{plant}/refresh/")

    assert response.status_code == 404
    sync_plant.assert_not_called()


def test_refresh_by_get_is_refused_and_calls_nobody(client_as) -> None:
    with mock.patch("cockpit.views.sync_plant") as sync_plant:
        response = client_as("Viewer").get("/plants/AUC1/refresh/")

    assert response.status_code == 405
    sync_plant.assert_not_called()


def test_refresh_without_sap_config_still_answers(client_as) -> None:
    response = client_as("Viewer").post("/plants/AUC1/refresh/", **HTMX)

    assert response.status_code == 204
    assert not PlantSnapshot.objects.exists()
