"""Fixtures for the acceptance tests: fixed clock, fake systems, logged-in users."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator

import pytest
import time_machine
from django.test import Client, override_settings

from tests.acceptance import builders
from tests.acceptance.support import NOW, Fakes, fake_systems


@pytest.fixture(autouse=True)
def _database(db) -> None:
    """Every acceptance test may use the database."""


@pytest.fixture
def clock() -> Iterator[time_machine.Coordinates]:
    """Freeze time at NOW (3 Nov 2026, 10:00 Amsterdam). Move it with `clock.move_to(...)`."""
    with time_machine.travel(NOW, tick=False) as traveller:
        yield traveller


@pytest.fixture
def running_clock() -> Iterator[time_machine.Coordinates]:
    """Like `clock`, but time keeps running: for browser tests, which need real timeouts."""
    with time_machine.travel(NOW, tick=True) as traveller:
        yield traveller


@pytest.fixture
def fakes() -> Iterator[Fakes]:
    """A fake SAP and a fake requisition mock, wired in through the settings."""
    with fake_systems() as active:
        yield active


@pytest.fixture
def client_as() -> Callable[..., Client]:
    """Return a test client logged in as a new user with the given role."""

    def login(role: str, username: str | None = None) -> Client:
        client = Client()
        client.force_login(builders.make_user(role, username))
        return client

    return login


@pytest.fixture
def live_sap() -> None:
    """Use the real SAP sandbox. Skips the test when SAP_API_KEY is not set (decision 3)."""
    if not os.environ.get("SAP_API_KEY"):
        pytest.skip("SAP_API_KEY is not set; this test reads the live SAP sandbox")


@pytest.fixture
def live_mock() -> Iterator[str]:
    """Use the real requisition mock, started locally (CI starts it). Yields its base URL."""
    base_url = os.environ.get("MOCK_PR_BASE_URL")
    api_key = os.environ.get("MOCK_API_KEY")
    if not (base_url and api_key):
        pytest.skip("MOCK_PR_BASE_URL and MOCK_API_KEY are not set; start the mock (mock_pr)")
    with override_settings(MOCK_PR_BASE_URL=base_url, MOCK_API_KEY=api_key):
        yield base_url


@pytest.fixture
def browser_as(page, live_server) -> Callable:
    """Log the Playwright page in as a user (a new one per role, or the one given).

    Returns a function `open(path, role=..., user=...)` that logs in and opens the path.
    """

    def open_as(path: str, role: str = "Planner", user=None):
        client = Client()
        client.force_login(user or builders.make_user(role))
        page.context.add_cookies(
            [
                {
                    "name": "sessionid",
                    "value": client.cookies["sessionid"].value,
                    "url": live_server.url,
                }
            ]
        )
        # A local page answers well within 5 s; the default 30 s only slows down red tests.
        page.set_default_timeout(5_000)
        page.goto(live_server.url + path)
        return page

    return open_as
