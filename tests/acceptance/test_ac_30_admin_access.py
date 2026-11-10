"""AC-30 (REQ-7): Admin can manage users and groups in /admin/ and gets 403 on business pages;
business roles get 403 on /admin/ user management."""

import pytest

from tests.acceptance.support import read_page

pytestmark = pytest.mark.xfail(strict=True, reason="Not built yet: #22")

ADMIN_PAGES = ["/admin/auth/user/", "/admin/auth/group/", "/admin/auth/user/add/"]
BUSINESS_PAGES = ["/orders/", "/requisitions/", "/dashboard/", "/settings/"]


def test_ac_30_admin_manages_users_and_groups(client_as):
    admin = client_as("Admin")

    for path in ADMIN_PAGES:
        assert admin.get(path).status_code == 200, path


def test_ac_30_admin_gets_403_on_business_pages(fakes, clock, client_as):
    admin = client_as("Admin")

    for path in BUSINESS_PAGES:
        response = admin.get(path)
        assert response.status_code == 403, path
        assert "You don't have permission for this" in read_page(response).text


@pytest.mark.parametrize("role", ["Viewer", "Planner", "Manager"])
def test_ac_30_business_roles_get_403_on_user_management(client_as, role):
    client = client_as(role)

    for path in ADMIN_PAGES:
        assert client.get(path).status_code == 403, path
