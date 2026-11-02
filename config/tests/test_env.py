"""Tests for the helpers that read settings from the environment and .env."""

import os
from pathlib import Path

import pytest

from config.env import database_from_url, env_bool, env_list, load_env_file, parse_env_line

BASE_DIR = Path("/project")


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


def test_database_from_url_relative_path_is_under_project() -> None:
    database = database_from_url("sqlite:///db.sqlite3", base_dir=BASE_DIR)

    assert database["ENGINE"] == "django.db.backends.sqlite3"
    assert database["NAME"] == Path("/project/db.sqlite3")


def test_database_from_url_keeps_absolute_path() -> None:
    database = database_from_url("sqlite:////var/data/db.sqlite3", base_dir=BASE_DIR)

    assert database["NAME"] == Path("/var/data/db.sqlite3")


@pytest.mark.parametrize(
    "url",
    [
        "",
        "sqlite://",
        "sqlite:///",
        "sqlite:///db.sqlite3?mode=ro",
        "sqlit:///db.sqlite3",
        "sqlite://host/db.sqlite3",
        "sqlite:///db.sqlite3#x",
        "postgres://user:secret@host/db",
    ],
)
def test_database_from_url_rejects_unsupported_urls(url: str) -> None:
    with pytest.raises(ValueError) as error:
        database_from_url(url, base_dir=BASE_DIR)

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
