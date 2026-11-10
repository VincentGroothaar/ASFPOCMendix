"""Shared test setup for the tests in this folder."""

import os

# Playwright's browser tests run an event loop in the test thread. Django then refuses
# database access ("You cannot call this from an async context"), although the test itself
# is not async. This flag tells Django the access is safe; it applies to tests only.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
