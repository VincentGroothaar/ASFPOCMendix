"""Top-level URL routes. Each app adds its own routes in its urls.py."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("cockpit.urls")),
]
