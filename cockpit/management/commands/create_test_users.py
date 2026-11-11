"""`manage.py create_test_users`: create or reset the five PoC accounts (#22).

Passwords come from TEST_PASSWORD_VIEWER, TEST_PASSWORD_PLANNER, TEST_PASSWORD_MANAGER_A,
TEST_PASSWORD_MANAGER_B and TEST_PASSWORD_ADMIN. It runs in the Render start command, so any
change made to these five accounts is undone on every restart.
"""

import os

from django.core.management.base import BaseCommand, CommandError

from cockpit.services.poc_accounts import (
    POC_ACCOUNTS,
    AccountSetupError,
    ensure_poc_accounts,
    passwords_from_environment,
)


class Command(BaseCommand):
    help = "Create or reset the PoC accounts viewer, planner, manager_a, manager_b and admin."

    def handle(self, *args, **options) -> None:
        try:
            passwords = passwords_from_environment(os.environ)
        except AccountSetupError as error:
            raise CommandError(f"No accounts were changed: {error}") from error
        ensure_poc_accounts(passwords)
        usernames = ", ".join(account.username for account in POC_ACCOUNTS)
        self.stdout.write(self.style.SUCCESS(f"PoC accounts are ready: {usernames}"))
