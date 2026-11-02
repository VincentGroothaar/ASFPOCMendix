"""Helpers that turn environment variables and the local .env file into settings."""

import os
from pathlib import Path
from urllib.parse import urlparse

TRUE_VALUES = {"1", "true", "yes", "on"}


def parse_env_line(line: str) -> tuple[str, str] | None:
    """Parse one line of a .env file into (key, value).

    Returns None for blank lines and comments. Accepts an optional leading
    `export`, removes matching quotes around the value, and drops a trailing
    ` # comment` from unquoted values. Raises ValueError for a malformed line.
    """
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if line.startswith("export "):
        line = line.removeprefix("export ").strip()
    if "=" not in line:
        raise ValueError(f"Expected KEY=value in .env, got: {line!r}")

    key, value = line.split("=", 1)
    key, value = key.strip(), value.strip()
    if not key:
        raise ValueError(f"Missing key before '=' in .env line: {line!r}")

    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    elif " #" in value:
        value = value.split(" #", 1)[0].rstrip()
    return key, value


def load_env_file(path: Path) -> None:
    """Load KEY=value lines from a local .env file into os.environ.

    Values already set in the real environment win, so CI and production
    are never overridden by a stray .env file.
    """
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        parsed = parse_env_line(line)
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
    if parsed.query:
        raise ValueError("DATABASE_URL options (?...) are not supported")

    # urlparse keeps one leading "/" from "sqlite:///"; remove it so a
    # relative path stays relative and "////" leaves an absolute path.
    file_path = parsed.path.removeprefix("/")
    if not file_path:
        raise ValueError("DATABASE_URL must name a database file, e.g. sqlite:///db.sqlite3")
    return {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": base_dir / file_path,
    }
