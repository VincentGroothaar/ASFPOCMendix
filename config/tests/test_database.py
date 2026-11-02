"""Tests that the app really talks to Postgres and keeps its password secret."""

import pytest
from django.db import connection
from django.test import RequestFactory
from django.views.debug import technical_500_response

# Kept up here: the debug page shows source lines around the error, and the
# test must only find the password if the page leaks the environment.
SECRET_PASSWORD = "topsecretpw"
SECRET_DATABASE_URL = f"postgresql://u:{SECRET_PASSWORD}@host/db"


@pytest.mark.django_db
def test_the_database_is_postgres_and_answers_a_query() -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        row = cursor.fetchone()

    assert connection.vendor == "postgresql"
    assert row == (1,)


def test_debug_error_page_hides_the_database_url(settings) -> None:
    settings.DEBUG = True
    request = RequestFactory().get("/", DATABASE_URL=SECRET_DATABASE_URL)

    try:
        raise RuntimeError("boom")
    except RuntimeError as error:
        response = technical_500_response(request, type(error), error, error.__traceback__)

    page = response.content.decode()
    assert "DATABASE_URL" in page
    assert SECRET_PASSWORD not in page
