"""INV-9: every page requires login, and every permission is checked on the server.
Anonymous requests redirect to login (also AC-29); forbidden actions return 403 even when sent
directly, without the button that would normally lead there."""

import pytest

from tests.acceptance import builders
from tests.acceptance.support import (
    ABOVE_LIMIT_CREATE,
    above_limit_plant,
    is_login_redirect,
    sync,
)

NOT_BUILT_34 = pytest.mark.xfail(strict=True, reason="Not built yet: #34")


@pytest.mark.parametrize(
    "path",
    [
        "/",  # built in #22
        "/orders/",  # built in #25
        pytest.param("/dashboard/", marks=NOT_BUILT_34),
        pytest.param("/requisitions/", marks=NOT_BUILT_34),
        pytest.param("/settings/", marks=NOT_BUILT_34),
    ],
)
def test_inv_9_anonymous_requests_go_to_login(client, path):
    assert is_login_redirect(client.get(path))


@pytest.mark.xfail(strict=True, reason="Not built yet: #34")
@pytest.mark.parametrize("role", ["Viewer", "Planner"])
def test_inv_9_only_a_manager_opens_and_saves_thresholds(client_as, role):
    client = client_as(role)

    assert client.get("/settings/").status_code == 403
    assert client.post("/settings/", builders.buffer_form("20")).status_code == 403


@pytest.mark.xfail(strict=True, reason="Not built yet: #33")
@pytest.mark.parametrize("role", ["Viewer", "Planner", "Admin"])
@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_inv_9_only_a_manager_decides_requisitions(fakes, clock, client_as, role, decision):
    above_limit_plant(fakes.sap)
    sync()
    client_as("Planner", "pat").post(ABOVE_LIMIT_CREATE, builders.requisition_form("60"))
    [waiting] = builders.requisitions()

    response = client_as(role).post(f"/requisitions/{waiting.id}/{decision}/")

    assert response.status_code == 403
    assert builders.requisitions()[0].status == builders.AWAITING_APPROVAL
