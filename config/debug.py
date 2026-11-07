"""Keeps secrets off Django's debug error page and out of error reports."""

import re

from django.views.debug import SafeExceptionReporterFilter


class ExceptionReporterFilter(SafeExceptionReporterFilter):
    """Django's default filter, plus DATABASE_URL, which contains the database password."""

    hidden_settings = re.compile(
        SafeExceptionReporterFilter.hidden_settings.pattern + "|DATABASE_URL",
        flags=re.IGNORECASE,
    )
