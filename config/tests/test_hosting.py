"""Tests for the hosted settings (DJANGO_HTTPS=true), as used on Render."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from django.contrib.auth.models import User
from django.test import Client

PROJECT_DIR = Path(__file__).resolve().parent.parent.parent

# Prints the hosting-related settings as JSON, so a test can read them back.
PRINT_SETTINGS = """
import json
from django.conf import settings
print(json.dumps({
    "debug": settings.DEBUG,
    "ssl_redirect": settings.SECURE_SSL_REDIRECT,
    "proxy_header": settings.SECURE_PROXY_SSL_HEADER,
    "session_cookie_secure": settings.SESSION_COOKIE_SECURE,
    "csrf_cookie_secure": settings.CSRF_COOKIE_SECURE,
}))
"""

# A request as Render's proxy passes it on: the public host name, and a header that says the
# browser used HTTPS.
RENDER_HOST = "cockpit.onrender.com"
VIA_HTTPS_PROXY = {"HTTP_HOST": RENDER_HOST, "HTTP_X_FORWARDED_PROTO": "https"}


def load_settings(**env: str) -> subprocess.CompletedProcess[str]:
    """Load the Django settings in a fresh process with the given environment variables."""
    # Values in the real environment win over .env, so a local .env cannot change the result.
    full_env = {**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings", **env}
    return subprocess.run(
        [sys.executable, "-c", PRINT_SETTINGS],
        cwd=PROJECT_DIR,
        env=full_env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_hosted_app_refuses_to_start_without_a_secret_key() -> None:
    result = load_settings(DJANGO_HTTPS="true", DJANGO_SECRET_KEY="")

    assert result.returncode != 0
    assert "DJANGO_SECRET_KEY is not set" in result.stderr


def test_hosted_app_uses_https_only() -> None:
    result = load_settings(
        DJANGO_HTTPS="true",
        DJANGO_SECRET_KEY="a-test-key-that-is-not-a-real-secret",
        DJANGO_DEBUG="false",
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "debug": False,
        "ssl_redirect": True,
        "proxy_header": ["HTTP_X_FORWARDED_PROTO", "https"],
        "session_cookie_secure": True,
        "csrf_cookie_secure": True,
    }


def test_local_app_runs_over_plain_http() -> None:
    result = load_settings(DJANGO_HTTPS="false")

    assert result.returncode == 0, result.stderr
    loaded = json.loads(result.stdout)
    assert loaded["ssl_redirect"] is False
    assert loaded["session_cookie_secure"] is False


@pytest.mark.django_db
def test_login_form_posted_over_the_https_proxy_passes_the_csrf_check(settings) -> None:
    settings.SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    settings.ALLOWED_HOSTS = [RENDER_HOST]
    User.objects.create_superuser("admin", password="a-test-password-only")
    client = Client(enforce_csrf_checks=True)

    client.get("/admin/login/", **VIA_HTTPS_PROXY)
    response = client.post(
        "/admin/login/",
        {
            "username": "admin",
            "password": "a-test-password-only",
            "csrfmiddlewaretoken": client.cookies["csrftoken"].value,
        },
        HTTP_ORIGIN=f"https://{RENDER_HOST}",
        **VIA_HTTPS_PROXY,
    )

    # A failed CSRF check would answer 403; a successful login redirects and logs the user in.
    assert response.status_code == 302
    assert "_auth_user_id" in client.session
