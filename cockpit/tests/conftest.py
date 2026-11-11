"""Shared fixtures for the cockpit tests: users with a role, or with a broken role."""

from collections.abc import Callable

import pytest
from django.contrib.auth.models import Group, User
from django.test import Client

PASSWORD = "a-long-test-password-31"


@pytest.fixture
def make_user(db) -> Callable[..., User]:
    """Create a user in the given groups (zero, one or several). The password is PASSWORD."""
    counter = iter(range(1, 1000))

    def make(*group_names: str, username: str | None = None, is_active: bool = True) -> User:
        user = User.objects.create_user(
            username or f"user{next(counter)}", password=PASSWORD, is_active=is_active
        )
        for name in group_names:
            group, _ = Group.objects.get_or_create(name=name)
            user.groups.add(group)
        return user

    return make


@pytest.fixture
def client_as(make_user) -> Callable[..., Client]:
    """Return a test client logged in as a new user in the given groups."""

    def login(*group_names: str) -> Client:
        client = Client()
        client.force_login(make_user(*group_names))
        return client

    return login


@pytest.fixture
def access_urls(settings) -> None:
    """Use the test-only URLconf with protected stand-in views (cockpit/tests/access_urls.py)."""
    settings.ROOT_URLCONF = "cockpit.tests.access_urls"
