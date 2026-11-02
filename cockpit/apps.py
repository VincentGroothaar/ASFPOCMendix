"""App configuration for the cockpit app."""

from django.apps import AppConfig


class CockpitConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "cockpit"
    verbose_name = "Material Shortage Cockpit"
