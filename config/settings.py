"""
Django settings for the Material Shortage Cockpit.

All environment-specific values come from environment variables.
For local development, copy `.env.example` to `.env` and fill in the values.
In Mendix terms, these are the app's constants.
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from config.env import database_from_url, env_bool, env_list, load_env_file

BASE_DIR = Path(__file__).resolve().parent.parent

load_env_file(BASE_DIR / ".env")

# --- Security ---------------------------------------------------------------

# DJANGO_HTTPS=true means the app is hosted behind an HTTPS proxy, as on Render.
# It is off locally and in CI, where the app runs over plain HTTP.
HOSTED_BEHIND_HTTPS = env_bool("DJANGO_HTTPS", default=False)

# The fallback key is only for local development and tests. A hosted app refuses
# to start without a real DJANGO_SECRET_KEY.
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "").strip()
if not SECRET_KEY:
    if HOSTED_BEHIND_HTTPS:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY is not set. A hosted app (DJANGO_HTTPS=true) needs a long "
            'random key, e.g. from `python -c "import secrets; print(secrets.token_urlsafe(50))"`.'
        )
    SECRET_KEY = "dev-only-insecure-key"
# DEBUG is off unless DJANGO_DEBUG says otherwise; .env.example turns it on locally.
DEBUG = env_bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", default="localhost,127.0.0.1")

if HOSTED_BEHIND_HTTPS:
    # Render sets RENDER_EXTERNAL_HOSTNAME to the service's public host name itself,
    # so the app accepts its own URL even when DJANGO_ALLOWED_HOSTS is not filled in.
    render_host = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "").strip()
    if render_host:
        ALLOWED_HOSTS.append(render_host)
    if any("/" in host for host in ALLOWED_HOSTS):
        raise ImproperlyConfigured(
            "DJANGO_ALLOWED_HOSTS must list host names only, e.g. cockpit.onrender.com "
            "without https:// or a path."
        )
    # Render's proxy handles HTTPS and tells the app so in the X-Forwarded-Proto header.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    # Send plain-HTTP visitors to HTTPS, and send cookies over HTTPS only. HSTS (telling
    # browsers to remember HTTPS) is left off: the redirect is enough for a demo app on a
    # shared onrender.com domain, and a wrong HSTS value is hard to undo in browsers.
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    # No CSRF_TRUSTED_ORIGINS needed: with the proxy header above, Django already accepts
    # forms posted from the app's own https://<host>.

# --- SAP (consumed OData service) -------------------------------------------

SAP_BASE_URL = os.environ.get("SAP_BASE_URL", "")
SAP_API_KEY = os.environ.get("SAP_API_KEY", "")

# --- Apps -------------------------------------------------------------------

INSTALLED_APPS = [
    # Django admin with the cockpit's role-based admin site (user administration, #22).
    "config.apps.CockpitAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "cockpit",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Serves the static files (CSS, admin styles) when hosted; must come right after security.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Every page needs a login unless a view is marked public (only the login page is).
    # HTMX requests get a whole-page redirect to the login page (#22, INV-9).
    "cockpit.access.HtmxLoginRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "cockpit.context_processors.sidebar",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --- Database ---------------------------------------------------------------

# Postgres in every environment; there is no SQLite fallback. Locally,
# `docker compose up -d` starts the database that .env.example points to.
# Lowercase on purpose: Django lists every UPPERCASE setting on its debug page,
# and this URL contains the database password. The debug page also lists the
# environment; ExceptionReporterFilter (below) hides DATABASE_URL there.
database_url = os.environ.get("DATABASE_URL", "")
if not database_url.strip():
    raise ImproperlyConfigured(
        "DATABASE_URL is not set. Copy .env.example to .env and run `docker compose up -d`."
    )
DATABASES = {"default": database_from_url(database_url)}

# Hide secrets, including DATABASE_URL, on the debug error page and in error reports.
DEFAULT_EXCEPTION_REPORTER_FILTER = "config.debug.ExceptionReporterFilter"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- Login and access (#22) ------------------------------------------------

LOGIN_URL = "/accounts/login/"
# After login everyone goes to "/": Admin is sent on to /admin/, business roles see the cockpit.
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/accounts/login/"
# A POST without a valid CSRF token gets the same 403 page as any other refusal.
CSRF_FAILURE_VIEW = "cockpit.views.csrf_failure"

# --- Language and time ------------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Europe/Amsterdam"
USE_I18N = True
USE_TZ = True

# --- Static files -----------------------------------------------------------

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
# `manage.py collectstatic` copies every static file here; WhiteNoise serves them from here.
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    # Also stores a compressed copy of each file, so pages load faster.
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Logging ----------------------------------------------------------------

# Django only prints errors to the console when DEBUG is on. With this, errors and warnings
# (a crash, a refused host name) also show up in the console when hosted: Render's logs.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO"},
        # The cockpit's own lines, e.g. one per plant sync with its duration (#24).
        "cockpit": {"handlers": ["console"], "level": "INFO"},
    },
}
