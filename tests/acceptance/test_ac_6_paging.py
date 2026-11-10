"""AC-6 (REQ-1): the list shows 50 orders per page; statuses on page 2 match a full calculation.

60 orders on the same day, each needing 10 PC of RM-1; stock 550 PC is allocated in order
number sequence. Order k gets 550 − 10 × (k − 1) available, so on page 2 (orders 51–60):
51–54 Covered (≥ 11 left), 55 Low cover (exactly 10), 56–60 Short (0). A calculation over
page 2 alone would show all of them Covered.
"""

import pytest

from tests.acceptance.support import Stock, days, one_component_order, read_page

pytestmark = pytest.mark.xfail(strict=True, reason="Not built yet: #25")


def number(k: int) -> str:
    return f"{1000100 + k}"


def test_ac_6_fifty_per_page_and_page_2_uses_the_full_calculation(fakes, clock, client_as):
    fakes.sap.orders += [
        one_component_order(number(k), days(1), "RM-1", "10") for k in range(1, 61)
    ]
    fakes.sap.stock.append(Stock("RM-1", 550))
    client = client_as("Viewer")

    first = read_page(client.get("/orders/"))
    second = read_page(client.get("/orders/", {"page": 2}))

    assert sum(number(k) in first.text for k in range(1, 61)) == 50
    assert sum(number(k) in second.text for k in range(1, 61)) == 10
    assert "Showing" in first.text and "60" in first.text
    for k in range(51, 55):
        assert "Covered" in second.row_with(number(k))
    assert "Low cover" in second.row_with(number(55))
    for k in range(56, 61):
        assert "Short" in second.row_with(number(k))
