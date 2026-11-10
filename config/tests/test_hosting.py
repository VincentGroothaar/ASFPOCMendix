"""Tests for the hosted settings (DJANGO_HTTPS=true), as used on Render.

Most tests load the real settings in a fresh Python process with the environment variables
Render would set, so they test config/settings.py itself and not a value set in the test.
"""

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

from django.core.management import call_command
from django.test import Client

PROJECT_DIR = Path(__file__).resolve().parent.parent.parent

RENDER_HOST = "cockpit.onrender.com"
# The environment of the app on Render; the key is a throwaway value for tests only.
HOSTED_ENV = {
    "DJANGO_HTTPS": "true",
    "DJANGO_DEBUG": "false",
    "DJANGO_SECRET_KEY": "a-test-key-that-is-not-a-real-secret",
    "DJANGO_ALLOWED_HOSTS": RENDER_HOST,
}

# Prints the hosting-related settings as JSON.
PRINT_SETTINGS = """
import json
from django.conf import settings
print(json.dumps({
    "debug": settings.DEBUG,
    "allowed_hosts": settings.ALLOWED_HOSTS,
    "ssl_redirect": settings.SECURE_SSL_REDIRECT,
    "proxy_header": settings.SECURE_PROXY_SSL_HEADER,
    "session_cookie_secure": settings.SESSION_COOKIE_SECURE,
    "csrf_cookie_secure": settings.CSRF_COOKIE_SECURE,
}))
"""

# Sends a login form through Django's CSRF check, the way Render's proxy passes it on
# (public host name, X-Forwarded-Proto: https), and prints "accepted" or the status code.
CHECK_CSRF = """
import sys
import django
django.setup()
from django.middleware.csrf import CsrfViewMiddleware, _get_new_csrf_string
from django.test import RequestFactory

host, origin = sys.argv[1], sys.argv[2]
token = _get_new_csrf_string()
request = RequestFactory().post(
    "/admin/login/",
    {"csrfmiddlewaretoken": token},
    HTTP_HOST=host,
    HTTP_ORIGIN=origin,
    HTTP_X_FORWARDED_PROTO="https",
)
request.COOKIES["csrftoken"] = token
middleware = CsrfViewMiddleware(lambda request: None)
middleware.process_request(request)
refused = middleware.process_view(request, lambda request: None, (), {})
print("accepted" if refused is None else refused.status_code)
"""


def run_python(code: str, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    """Run Python code in a fresh process with the Django settings and the given variables."""
    # Values in the real environment win over .env, so a local .env cannot change the result.
    full_env = {**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings", **env}
    return subprocess.run(
        [sys.executable, "-c", code, *args],
        cwd=PROJECT_DIR,
        env=full_env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_hosted_app_refuses_to_start_without_a_secret_key() -> None:
    for empty_key in ["", "   "]:
        result = run_python(PRINT_SETTINGS, {**HOSTED_ENV, "DJANGO_SECRET_KEY": empty_key})

        assert result.returncode != 0
        assert "DJANGO_SECRET_KEY is not set" in result.stderr


def test_hosted_app_uses_https_only() -> None:
    result = run_python(PRINT_SETTINGS, HOSTED_ENV)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "debug": False,
        "allowed_hosts": [RENDER_HOST],
        "ssl_redirect": True,
        "proxy_header": ["HTTP_X_FORWARDED_PROTO", "https"],
        "session_cookie_secure": True,
        "csrf_cookie_secure": True,
    }


def test_hosted_app_accepts_the_host_name_render_gives_it() -> None:
    env = {**HOSTED_ENV, "DJANGO_ALLOWED_HOSTS": "", "RENDER_EXTERNAL_HOSTNAME": RENDER_HOST}

    result = run_python(PRINT_SETTINGS, env)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["allowed_hosts"] == [RENDER_HOST]


def test_hosted_app_refuses_a_url_instead_of_a_host_name() -> None:
    env = {**HOSTED_ENV, "DJANGO_ALLOWED_HOSTS": f"https://{RENDER_HOST}"}

    result = run_python(PRINT_SETTINGS, env)

    assert result.returncode != 0
    assert "host names only" in result.stderr


def test_local_app_runs_over_plain_http() -> None:
    result = run_python(PRINT_SETTINGS, {"DJANGO_HTTPS": "false"})

    assert result.returncode == 0, result.stderr
    loaded = json.loads(result.stdout)
    assert loaded["ssl_redirect"] is False
    assert loaded["session_cookie_secure"] is False


def test_hosted_app_accepts_forms_posted_from_its_own_https_address() -> None:
    result = run_python(CHECK_CSRF, HOSTED_ENV, RENDER_HOST, f"https://{RENDER_HOST}")

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "accepted"


def test_hosted_app_refuses_forms_posted_from_another_site() -> None:
    result = run_python(CHECK_CSRF, HOSTED_ENV, RENDER_HOST, "https://evil.example")

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "403"


def test_collected_static_files_are_served_with_debug_off(settings, tmp_path) -> None:
    # `collectstatic` in the Render build command fails without a STATIC_ROOT.
    assert settings.STATIC_ROOT
    settings.DEBUG = False
    settings.STATIC_ROOT = tmp_path
    call_command("collectstatic", interactive=False, verbosity=0)

    # A new client starts the middleware again, so WhiteNoise finds the files in tmp_path.
    response = Client().get("/static/admin/css/base.css")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/css")


def test_errors_reach_the_console_with_debug_off(settings) -> None:
    settings.DEBUG = False
    error = logging.LogRecord("django.request", logging.ERROR, __file__, 0, "boom", None, None)

    console_handlers = [
        handler
        for handler in logging.getLogger("django").handlers
        if type(handler) is logging.StreamHandler
    ]

    assert any(handler.filter(error) for handler in console_handlers)
