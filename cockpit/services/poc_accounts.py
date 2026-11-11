"""The five PoC accounts for local use, CI and the jury (#22).

`create_test_users` calls these functions. The module is not named `test_users.py` because
pytest would then collect it as a test file.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from django.contrib.auth.models import Group, User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction

from cockpit.services.roles import Role


@dataclass(frozen=True)
class PocAccount:
    """One PoC account: its username, its role and the variable that holds its password."""

    username: str
    role: Role
    password_variable: str


POC_ACCOUNTS: tuple[PocAccount, ...] = (
    PocAccount("viewer", Role.VIEWER, "TEST_PASSWORD_VIEWER"),
    PocAccount("planner", Role.PLANNER, "TEST_PASSWORD_PLANNER"),
    PocAccount("manager_a", Role.MANAGER, "TEST_PASSWORD_MANAGER_A"),
    PocAccount("manager_b", Role.MANAGER, "TEST_PASSWORD_MANAGER_B"),
    PocAccount("admin", Role.ADMIN, "TEST_PASSWORD_ADMIN"),
)


class AccountSetupError(Exception):
    """A password is missing or too weak. The message names the variable, never the value."""


def passwords_from_environment(environment: Mapping[str, str]) -> dict[str, str]:
    """Read and check every PoC password. Returns {username: password}.

    Raises AccountSetupError listing every variable that is missing or fails Django's password
    rules, so nothing is changed when any one of them is wrong.
    """
    passwords: dict[str, str] = {}
    problems: list[str] = []
    for account in POC_ACCOUNTS:
        password = environment.get(account.password_variable, "")
        if not password:
            problems.append(f"{account.password_variable} is not set")
            continue
        try:
            validate_password(password, user=User(username=account.username))
        except ValidationError as error:
            problems.append(f"{account.password_variable} is too weak: {' '.join(error.messages)}")
            continue
        passwords[account.username] = password
    if problems:
        raise AccountSetupError("; ".join(problems))
    return passwords


@transaction.atomic
def ensure_poc_accounts(passwords: Mapping[str, str]) -> None:
    """Create or fully reset the five PoC accounts. No other user is touched.

    Each account gets its password, exactly its own role, and is active, not staff and not
    superuser. Running it again gives the same result, which is why it can run on every start.
    """
    for account in POC_ACCOUNTS:
        user, _ = User.objects.get_or_create(username=account.username)
        user.set_password(passwords[account.username])
        user.is_active = True
        user.is_staff = False
        user.is_superuser = False
        user.save()
        role_group, _ = Group.objects.get_or_create(name=account.role.value)
        user.groups.set([role_group])
        user.user_permissions.clear()
