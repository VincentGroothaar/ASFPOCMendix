"""CSRF tokens for the SAP-style handshake: fetch a token with a GET, send it back with the POST.

A token is a random part plus a signature made with a server secret. The mock can check a
token without storing it, so tokens keep working when Render runs the mock on a new instance.
"""

import hashlib
import hmac
import secrets


def new_token(secret: str) -> str:
    """Return a new CSRF token signed with `secret`."""
    random_part = secrets.token_urlsafe(16)
    return f"{random_part}.{_signature(random_part, secret)}"


def is_valid_token(token: str | None, secret: str) -> bool:
    """Return True if `token` was made by new_token with the same secret."""
    if not token or "." not in token:
        return False
    random_part, signature = token.rsplit(".", 1)
    return hmac.compare_digest(signature, _signature(random_part, secret))


def _signature(random_part: str, secret: str) -> str:
    return hmac.new(secret.encode(), random_part.encode(), hashlib.sha256).hexdigest()
