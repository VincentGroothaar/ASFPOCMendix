"""URL routes of the cockpit app."""

from django.urls import path

from cockpit import views

app_name = "cockpit"

urlpatterns = [
    path("", views.home, name="home"),
]
