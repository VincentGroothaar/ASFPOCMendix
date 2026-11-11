"""Tests for `manage.py create_test_users` (AC-43)."""

import pytest
from django.contrib.auth.models import Group, User
from django.core.management import CommandError, call_command

from cockpit.services.poc_accounts import POC_ACCOUNTS
from cockpit.services.roles import role_of

EXPECTED_ROLES = {
    "viewer": "Viewer",
    "planner": "Planner",
    "manager_a": "Manager",
    "manager_b": "Manager",
    "admin": "Admin",
}


def password_for(username: str) -> str:
    return f"jury-{username}-passphrase-2026"


@pytest.fixture
def passwords(monkeypatch) -> None:
    for account in POC_ACCOUNTS:
        monkeypatch.setenv(account.password_variable, password_for(account.username))


def test_creates_the_five_accounts_with_their_roles(db, passwords) -> None:
    call_command("create_test_users")

    for username, role in EXPECTED_ROLES.items():
        user = User.objects.get(username=username)
        assert role_of(user).value == role
        assert user.check_password(password_for(username))
        assert user.is_active and not user.is_staff and not user.is_superuser


def test_a_rerun_resets_changed_accounts_and_leaves_other_users_alone(db, passwords) -> None:
    call_command("create_test_users")
    other = User.objects.create_user("someone", password="x")
    tampered = User.objects.get(username="manager_b")
    tampered.set_password("changed")
    tampered.is_active = False
    tampered.is_staff = True
    tampered.is_superuser = True
    tampered.save()
    tampered.groups.set([Group.objects.get(name="Admin"), Group.objects.get(name="Viewer")])

    call_command("create_test_users")

    tampered.refresh_from_db()
    assert role_of(tampered).value == "Manager"
    assert tampered.check_password(password_for("manager_b"))
    assert tampered.is_active and not tampered.is_staff and not tampered.is_superuser
    assert User.objects.filter(username__in=EXPECTED_ROLES).count() == 5
    other.refresh_from_db()
    assert other.check_password("x")


def test_works_when_the_role_groups_are_missing(db, passwords) -> None:
    Group.objects.all().delete()

    call_command("create_test_users")

    assert role_of(User.objects.get(username="admin")).value == "Admin"


def test_a_missing_password_changes_nothing(db, passwords, monkeypatch) -> None:
    monkeypatch.delenv("TEST_PASSWORD_ADMIN")

    with pytest.raises(CommandError, match="TEST_PASSWORD_ADMIN is not set"):
        call_command("create_test_users")

    assert not User.objects.exists()


def test_a_weak_password_is_named_but_never_printed(db, passwords, monkeypatch) -> None:
    monkeypatch.setenv("TEST_PASSWORD_PLANNER", "12345678")

    with pytest.raises(CommandError) as raised:
        call_command("create_test_users")

    assert "TEST_PASSWORD_PLANNER is too weak" in str(raised.value)
    assert "12345678" not in str(raised.value)
    assert not User.objects.exists()
