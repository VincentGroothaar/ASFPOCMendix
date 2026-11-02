"""Views handle the HTTP request and render a template.

Keep business logic out of here: put it in `cockpit/services/` and call it.
"""

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


def home(request: HttpRequest) -> HttpResponse:
    """Show the cockpit start page."""
    return render(request, "cockpit/home.html")
