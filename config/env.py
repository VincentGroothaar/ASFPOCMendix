"""Helpers that turn environment variables and the local .env file into settings."""

import os
from pathlib import Path
from urllib.parse import unquote, urlparse

TRUE_VALUES = {"1", "true", "yes", "on"}
POSTGRES_SCHEMES = {"postgres", "postgresql"}
ENCODE_HINT = "Percent-encode special characters in the password, e.g. @ as %40 and / as %2F."


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


def database_from_url(url: str) -> dict:
    """Turn a DATABASE_URL into a Django DATABASES entry for Postgres.

    Expects postgresql://user:password@host:port/database (the scheme may also
    be postgres://). Special characters in the user or password must be
    percent-encoded, e.g. "p@ss" as "p%40ss"; they are decoded here.
    Raises ValueError for anything else. The error never contains the URL,
    so the password cannot end up in a log.
    """
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        raise ValueError(f"DATABASE_URL could not be read. {ENCODE_HINT}") from None
    if parsed.scheme not in POSTGRES_SCHEMES:
        raise ValueError(
            f"Unsupported DATABASE_URL scheme {parsed.scheme!r}: only Postgres is supported, "
            "e.g. postgresql://cockpit:cockpit@localhost:5432/cockpit"
        )
    if parsed.query or parsed.fragment:
        raise ValueError(f"DATABASE_URL must not contain options after '?' or '#'. {ENCODE_HINT}")

    try:
        port = parsed.port
    except ValueError:
        raise ValueError(f"DATABASE_URL has a port that is not a number. {ENCODE_HINT}") from None
    name = unquote(parsed.path.removeprefix("/"))
    if not parsed.hostname or not name or "/" in name:
        raise ValueError(
            "DATABASE_URL must name a host and a database, e.g. "
            "postgresql://cockpit:cockpit@localhost:5432/cockpit"
        )

    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": name,
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname,
        "PORT": "" if port is None else str(port),
    }
