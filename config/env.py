"""Helpers that turn environment variables and the local .env file into settings."""

import os
from pathlib import Path
from urllib.parse import urlparse

TRUE_VALUES = {"1", "true", "yes", "on"}


def parse_env_line(line: str) -> tuple[str, str] | None:
    """Parse one line of a .env file into (key, value).

    Returns None for blank lines and comments. Accepts an optional leading
    `export`, removes quotes around the value, and drops a trailing
    ` # comment`. Raises ValueError for a malformed line. The error never
    contains the value, so a secret cannot end up in a log.
    """
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if line.startswith("export "):
        line = line.removeprefix("export ").strip()
    if "=" not in line:
        raise ValueError("expected KEY=value")

    key, value = line.split("=", 1)
    key, value = key.strip(), value.strip()
    if not key or any(char.isspace() for char in key):
        raise ValueError("the key before '=' is missing or contains spaces")

    if value[:1] in ('"', "'"):
        quote = value[0]
        closing = value.find(quote, 1)
        rest = value[closing + 1 :].strip() if closing != -1 else ""
        if closing == -1 or (rest and not rest.startswith("#")):
            raise ValueError(f"the value of {key} has an unmatched quote")
        return key, value[1:closing]

    if " #" in value:
        value = value.split(" #", 1)[0].rstrip()
    return key, value


def load_env_file(path: Path) -> None:
    """Load KEY=value lines from a local .env file into os.environ.

    Values already set in the real environment win, so CI and production
    are never overridden by a stray .env file.
    """
    if not path.exists():
        return
    # utf-8-sig ignores the invisible byte-order mark some editors add.
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    for number, line in enumerate(lines, start=1):
        try:
            parsed = parse_env_line(line)
        except ValueError as error:
            raise ValueError(f"{path.name} line {number}: {error}") from None
        if parsed:
            key, value = parsed
            os.environ.setdefault(key, value)


def env_bool(name: str, default: bool) -> bool:
    """Read a yes/no environment variable. `1`, `true`, `yes` and `on` mean yes."""
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in TRUE_VALUES


def env_list(name: str, default: str) -> list[str]:
    """Read a comma-separated environment variable as a list, skipping empty items."""
    value = os.environ.get(name, default)
    return [item.strip() for item in value.split(",") if item.strip()]


def database_from_url(url: str, base_dir: Path) -> dict:
    """Turn a DATABASE_URL into a Django DATABASES entry.

    Only SQLite is supported for now. `sqlite:///db.sqlite3` is a file relative
    to `base_dir`; `sqlite:////var/data/db.sqlite3` is an absolute path.
    Add other databases when a story needs them.
    """
    parsed = urlparse(url)
    if parsed.scheme != "sqlite":
        raise ValueError(f"Unsupported DATABASE_URL scheme: {parsed.scheme!r}")
    if parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError(
            "DATABASE_URL must look like sqlite:///db.sqlite3, without host or options"
        )

    # urlparse keeps one leading "/" from "sqlite:///"; remove it so a
    # relative path stays relative and "////" leaves an absolute path.
    file_path = parsed.path.removeprefix("/")
    if not file_path:
        raise ValueError("DATABASE_URL must name a database file, e.g. sqlite:///db.sqlite3")
    return {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": base_dir / file_path,
    }
