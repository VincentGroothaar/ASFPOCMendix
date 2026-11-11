"""Top-level URL routes. Each app adds its own routes in its urls.py."""

from django.contrib import admin
from django.contrib.auth.views import LoginView
from django.urls import include, path

from cockpit.views import CockpitLogoutView

urlpatterns = [
    path("admin/", admin.site.urls),
    # The login page is the only page anyone can open without logging in.
    path("accounts/login/", LoginView.as_view(), name="login"),
    path("accounts/logout/", CockpitLogoutView.as_view(), name="logout"),
    path("", include("cockpit.urls")),
]

# Every refused page or action renders the cockpit 403 page (ui-spec 4.7 E).
handler403 = "cockpit.views.permission_denied"
