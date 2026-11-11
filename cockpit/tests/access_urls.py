"""A test-only URLconf: the app's own URLs plus a few protected views to test access on.

The business pages arrive in later issues; these stand-ins let the tests prove the access
mechanism now. Tests switch to it with `settings.ROOT_URLCONF = "cockpit.tests.access_urls"`.
It is never included in the app's own URLs.
"""

from django.contrib.auth.models import Group
from django.http import HttpRequest, HttpResponse
from django.template import RequestContext, Template
from django.urls import path

from cockpit.access import requires
from cockpit.services.roles import Action
from config.urls import urlpatterns as app_urlpatterns

# A view that would store something: tests check that a refused POST stores nothing.
STORED_GROUP_NAME = "stored-by-protected-post"

HTMX_PAGE = Template(
    """{% extends "base.html" %}
{% block content %}
  <h1>Test page</h1>
  <p id="target">Untouched</p>
  <button id="forbidden" hx-get="/test/forbidden/" hx-target="#target"
          hx-swap="outerHTML" hx-select="#not-in-response">Forbidden action</button>
  <button id="allowed" hx-get="/test/allowed/" hx-target="#target">Allowed action</button>
{% endblock %}"""
)


@requires(Action.VIEW_BUSINESS)
def business_page(request: HttpRequest) -> HttpResponse:
    """A business page with HTMX buttons, for the browser tests."""
    return HttpResponse(HTMX_PAGE.render(RequestContext(request)))


@requires(Action.VIEW_BUSINESS)
def allowed_fragment(request: HttpRequest) -> HttpResponse:
    return HttpResponse('<p id="target">Allowed fragment</p>')


@requires(Action.MANAGE_USERS)
def forbidden_fragment(request: HttpRequest) -> HttpResponse:
    """Only Admin may do this, so every business role gets 403."""
    return HttpResponse('<p id="target">Should never be shown to business roles</p>')


@requires(Action.CREATE_REQUISITION)
def protected_post(request: HttpRequest) -> HttpResponse:
    """Stands in for creating a requisition (INV-1): stores a row when allowed."""
    Group.objects.create(name=STORED_GROUP_NAME)
    return HttpResponse("stored")


urlpatterns = [
    path("test/page/", business_page),
    path("test/allowed/", allowed_fragment),
    path("test/forbidden/", forbidden_fragment),
    path("test/create/", protected_post),
    *app_urlpatterns,
]

handler403 = "cockpit.views.permission_denied"
