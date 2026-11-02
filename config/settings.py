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

# The fallback key is only for local development and tests. Set a real
# DJANGO_SECRET_KEY in any shared or deployed environment.
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or "dev-only-insecure-key"
# DEBUG is off unless DJANGO_DEBUG says otherwise; .env.example turns it on locally.
DEBUG = env_bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", default="localhost,127.0.0.1")

# --- SAP (consumed OData service) -------------------------------------------

SAP_BASE_URL = os.environ.get("SAP_BASE_URL", "")
SAP_API_KEY = os.environ.get("SAP_API_KEY", "")

# --- Apps -------------------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "cockpit",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
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
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --- Database ---------------------------------------------------------------

# Postgres in every environment; there is no SQLite fallback. Locally,
# `docker compose up -d` starts the database that .env.example points to.
# Lowercase on purpose: Django's debug page lists every UPPERCASE setting,
# and this URL contains the database password.
database_url = os.environ.get("DATABASE_URL", "")
if not database_url.strip():
    raise ImproperlyConfigured(
        "DATABASE_URL is not set. Copy .env.example to .env and run `docker compose up -d`."
    )
DATABASES = {"default": database_from_url(database_url)}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- Language and time ------------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Europe/Amsterdam"
USE_I18N = True
USE_TZ = True

# --- Static files -----------------------------------------------------------

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
