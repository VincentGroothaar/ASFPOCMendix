"""Create the four role groups (REQ-7), so every database has them.

The names are written out here instead of imported from cockpit.services.roles: a migration
must keep working even if the code it was written against changes later.
"""

from django.db import migrations

ROLE_GROUP_NAMES = ["Viewer", "Planner", "Manager", "Admin"]


def create_role_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    for name in ROLE_GROUP_NAMES:
        Group.objects.get_or_create(name=name)


def delete_role_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name__in=ROLE_GROUP_NAMES).delete()


class Migration(migrations.Migration):
    dependencies = [("auth", "0012_alter_user_first_name_max_length")]

    operations = [migrations.RunPython(create_role_groups, delete_role_groups)]
