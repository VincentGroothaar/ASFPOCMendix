"""User administration in Django admin, for the Admin role only (REQ-7).

The Admin manages users and gives each one exactly one role. Role groups can be viewed but
not changed, and business models are not registered here. Who may open these screens is
decided by the role table (`cockpit/services/roles.py`), not by Django's staff flag.
"""

from django import forms
from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin, UserAdmin
from django.contrib.auth.forms import AdminUserCreationForm, UserChangeForm
from django.contrib.auth.models import Group, User
from django.db.models import QuerySet
from django.http import HttpRequest

from cockpit.services.roles import ROLE_GROUP_NAMES, Action, can, role_of

EXACTLY_ONE_ROLE = "Choose exactly one role."


def role_field() -> forms.ModelMultipleChoiceField:
    """The Role field: the role groups as checkboxes, of which exactly one must be ticked."""
    return forms.ModelMultipleChoiceField(
        queryset=Group.objects.filter(name__in=ROLE_GROUP_NAMES).order_by("name"),
        widget=forms.CheckboxSelectMultiple,
        label="Role",
        required=True,
        error_messages={"required": EXACTLY_ONE_ROLE},
    )


def check_exactly_one_role(groups: QuerySet[Group] | None) -> QuerySet[Group]:
    """Form validation shared by the add and change forms: exactly one role group."""
    if groups is None or len(groups) != 1:
        raise forms.ValidationError(EXACTLY_ONE_ROLE)
    return groups


class CockpitUserCreationForm(AdminUserCreationForm):
    """The Add user form, with the role required."""

    groups = role_field()

    class Meta(AdminUserCreationForm.Meta):
        fields = ("username", "groups")

    def clean_groups(self) -> QuerySet[Group]:
        """Refuse a new user with zero or several roles."""
        return check_exactly_one_role(self.cleaned_data.get("groups"))


class CockpitUserChangeForm(UserChangeForm):
    """The Change user form, with the role required."""

    groups = role_field()

    def clean_groups(self) -> QuerySet[Group]:
        """Refuse saving a user with zero or several roles."""
        return check_exactly_one_role(self.cleaned_data.get("groups"))


class AdminRoleOnly:
    """Every admin permission check asks the role table: only the Admin role may manage users."""

    def has_module_permission(self, request: HttpRequest) -> bool:
        """Show the model on the admin index only to the Admin role."""
        return can(request.user, Action.MANAGE_USERS)

    def has_view_permission(self, request: HttpRequest, obj: object | None = None) -> bool:
        """Only the Admin role may view users and groups."""
        return can(request.user, Action.MANAGE_USERS)


class CockpitUserAdmin(AdminRoleOnly, UserAdmin):
    """Users: username, name, email, active and exactly one role. No staff or permissions."""

    form = CockpitUserChangeForm
    add_form = CockpitUserCreationForm
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name", "email")}),
        ("Access", {"fields": ("is_active", "groups")}),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "usable_password", "password1", "password2", "groups"),
            },
        ),
    )
    list_display = ("username", "first_name", "last_name", "role", "is_active")
    list_filter = ("is_active", "groups")
    filter_horizontal = ()

    @admin.display(description="Role")
    def role(self, user: User) -> str:
        """The user's role for the list, or "No role" for a broken account."""
        role = role_of(user)
        return role.value if role else "No role"

    def has_add_permission(self, request: HttpRequest) -> bool:
        return can(request.user, Action.MANAGE_USERS)

    def has_change_permission(self, request: HttpRequest, obj: object | None = None) -> bool:
        return can(request.user, Action.MANAGE_USERS)

    def has_delete_permission(self, request: HttpRequest, obj: object | None = None) -> bool:
        return can(request.user, Action.MANAGE_USERS)


class CockpitGroupAdmin(AdminRoleOnly, GroupAdmin):
    """Role groups: view only. Renaming or deleting one would break the role table."""

    fields = ("name",)
    filter_horizontal = ()

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: object | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: object | None = None) -> bool:
        return False


# django.contrib.auth registers its own User and Group admins; replace them.
admin.site.unregister(User)
admin.site.unregister(Group)
admin.site.register(User, CockpitUserAdmin)
admin.site.register(Group, CockpitGroupAdmin)
