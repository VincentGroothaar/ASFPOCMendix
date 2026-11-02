"""Tests that Django refuses to start without a Postgres DATABASE_URL."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parent.parent.parent


def run_manage_check(database_url: str) -> subprocess.CompletedProcess[str]:
    """Run `manage.py check` in a fresh process with the given DATABASE_URL."""
    # A value in the real environment wins over .env, so a local .env cannot hide the error.
    env = {**os.environ, "DATABASE_URL": database_url}
    return subprocess.run(
        [sys.executable, "manage.py", "check"],
        cwd=PROJECT_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.mark.parametrize(
    ("database_url", "message"),
    [
        ("sqlite:///db.sqlite3", "only Postgres is supported"),
        ("", "DATABASE_URL is not set"),
    ],
)
def test_django_stops_with_a_clear_error_without_a_postgres_url(
    database_url: str, message: str
) -> None:
    result = run_manage_check(database_url)

    assert result.returncode != 0
    assert message in result.stderr
