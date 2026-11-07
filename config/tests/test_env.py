"""Tests for the helpers that read settings from the environment and .env."""

import os
from pathlib import Path

import pytest

from config.env import database_from_url, env_bool, env_list, load_env_file, parse_env_line


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("SAP_API_KEY=abc", ("SAP_API_KEY", "abc")),
        ("  SAP_API_KEY = abc  ", ("SAP_API_KEY", "abc")),
        ('SAP_API_KEY="abc"', ("SAP_API_KEY", "abc")),
        ("SAP_API_KEY='abc'", ("SAP_API_KEY", "abc")),
        ("export SAP_API_KEY=abc", ("SAP_API_KEY", "abc")),
        ("SAP_API_KEY=abc # my key", ("SAP_API_KEY", "abc")),
        ('SAP_API_KEY="abc # not a comment"', ("SAP_API_KEY", "abc # not a comment")),
        ('SAP_API_KEY="abc" # my key', ("SAP_API_KEY", "abc")),
        ("SAP_API_KEY='abc'   # my key", ("SAP_API_KEY", "abc")),
        ('SAP_API_KEY=""', ("SAP_API_KEY", "")),
        ("SAP_API_KEY=", ("SAP_API_KEY", "")),
        ("URL=https://x.test/?a=b", ("URL", "https://x.test/?a=b")),
    ],
)
def test_parse_env_line_reads_key_and_value(line: str, expected: tuple[str, str]) -> None:
    assert parse_env_line(line) == expected


@pytest.mark.parametrize("line", ["", "   ", "# a comment", "  # indented comment"])
def test_parse_env_line_skips_blank_lines_and_comments(line: str) -> None:
    assert parse_env_line(line) is None


@pytest.mark.parametrize(
    "line",
    [
        "=oops",
        "  = value",
        "SAP_API_KEY sk-secret",
        "MY KEY=sk-secret",
        'SAP_API_KEY="sk-secret',
        'SAP_API_KEY="sk-secret" extra',
    ],
)
def test_parse_env_line_rejects_malformed_lines_without_showing_the_value(line: str) -> None:
    with pytest.raises(ValueError) as error:
        parse_env_line(line)

    assert "sk-secret" not in str(error.value)


def test_load_env_file_keeps_values_already_in_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("\ufeffFROM_FILE=file\nALREADY_SET=file\n", encoding="utf-8")
    monkeypatch.delenv("FROM_FILE", raising=False)
    monkeypatch.setenv("ALREADY_SET", "real")

    load_env_file(env_file)

    assert os.environ["FROM_FILE"] == "file"
    assert os.environ["ALREADY_SET"] == "real"


def test_load_env_file_reports_the_line_number(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("GOOD=1\nBROKEN\n")

    with pytest.raises(ValueError, match="line 2"):
        load_env_file(env_file)


def test_database_from_url_maps_a_postgres_url_to_django_settings() -> None:
    database = database_from_url("postgresql://cockpit:cockpit@db.local:5433/cockpit")

    assert database == {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "cockpit",
        "USER": "cockpit",
        "PASSWORD": "cockpit",
        "HOST": "db.local",
        "PORT": "5433",
    }


def test_database_from_url_accepts_the_short_postgres_scheme_and_default_port() -> None:
    database = database_from_url("postgres://cockpit:cockpit@localhost/cockpit")

    assert database["ENGINE"] == "django.db.backends.postgresql"
    assert database["PORT"] == ""


def test_database_from_url_decodes_special_characters_in_user_and_password() -> None:
    database = database_from_url("postgresql://app%2Buser:p%40ss%3Aw%2Fo%23rd%25@localhost/cockpit")

    assert database["USER"] == "app+user"
    assert database["PASSWORD"] == "p@ss:w/o#rd%"


@pytest.mark.parametrize(
    "url",
    ["sqlite:///db.sqlite3", "sqlite:////var/data/db.sqlite3", "mysql://u:secret@host/db", ""],
)
def test_database_from_url_rejects_other_databases_with_a_clear_error(url: str) -> None:
    with pytest.raises(ValueError, match="only Postgres is supported"):
        database_from_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://u:secret@host",
        "postgresql://u:secret@host/",
        "postgresql://u:secret@/db",
        "postgresql://u:secret@host/db/extra",
        "postgresql://u:secret@host:abc/db",
        "postgresql://u:secret@host:99999/db",
        "postgresql://u:secret@host/db?sslmode=require",
        "postgresql://u:secret@host/db#x",
    ],
)
def test_database_from_url_rejects_incomplete_postgres_urls_without_showing_the_password(
    url: str,
) -> None:
    with pytest.raises(ValueError) as error:
        database_from_url(url)

    assert "secret" not in str(error.value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("true", True),
        ("TRUE", True),
        (" yes ", True),
        ("1", True),
        ("on", True),
        ("false", False),
        ("0", False),
        ("no", False),
        ("nonsense", False),
    ],
)
def test_env_bool_reads_yes_and_no(
    monkeypatch: pytest.MonkeyPatch, value: str, expected: bool
) -> None:
    monkeypatch.setenv("FLAG", value)

    assert env_bool("FLAG", default=False) is expected


@pytest.mark.parametrize("value", [None, "", "   "])
def test_env_bool_uses_default_when_unset_or_empty(
    monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    if value is None:
        monkeypatch.delenv("FLAG", raising=False)
    else:
        monkeypatch.setenv("FLAG", value)

    assert env_bool("FLAG", default=True) is True


def test_env_list_splits_on_commas_and_skips_empty_items(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOSTS", " a.test , ,b.test,, ")

    assert env_list("HOSTS", default="") == ["a.test", "b.test"]


def test_database_from_url_keeps_an_explicit_port_zero() -> None:
    assert database_from_url("postgresql://u:p@host:0/db")["PORT"] == "0"


@pytest.mark.parametrize(
    "url",
    ["postgresql://u:p/ss@host/db", "postgresql://u:p#ss@host/db", "postgresql://u:p@[::1/db"],
)
def test_database_from_url_suggests_percent_encoding_for_a_broken_password(url: str) -> None:
    with pytest.raises(ValueError, match="Percent-encode"):
        database_from_url(url)
