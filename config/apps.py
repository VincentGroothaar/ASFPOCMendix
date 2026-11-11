"""App configuration that replaces Django's default admin site with the cockpit's own.

It lives here and not in `cockpit/apps.py`: with two AppConfig classes in one module, Django
would no longer pick `CockpitConfig` for the cockpit app automatically.
"""

from django.contrib.admin.apps import AdminConfig


class CockpitAdminConfig(AdminConfig):
    """Django admin, but `admin.site` is the role-based `CockpitAdminSite`."""

    default_site = "cockpit.admin_site.CockpitAdminSite"
