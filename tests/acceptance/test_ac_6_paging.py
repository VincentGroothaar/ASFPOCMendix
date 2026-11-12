"""AC-6 (REQ-1): the list shows 50 orders per page; statuses on page 2 match a full calculation.

60 orders, order k starting k days from today, each needing 10 PC of RM-1; stock 550 PC is
allocated in start-date order. Every order has its own date, so the order on the pages does not
depend on a tie-breaker. The range is widened to cover all 60. Order k gets
550 − 10 × (k − 1) available, so on page 2 (orders 51–60):
51–54 Covered (≥ 11 left), 55 Low cover (exactly 10), 56–60 Short (0). A calculation over
page 2 alone would show all of them Covered.
"""

from tests.acceptance.support import PLANT, Stock, days, one_component_order, read_page


def number(k: int) -> str:
    return f"{1000100 + k}"


def test_ac_6_fifty_per_page_and_page_2_uses_the_full_calculation(fakes, clock, client_as):
    fakes.sap.orders += [
        one_component_order(number(k), days(k), "RM-1", "10") for k in range(1, 61)
    ]
    fakes.sap.stock.append(Stock("RM-1", 550))
    client = client_as("Viewer")
    wide = {"plant": PLANT, "from": days(0), "to": days(70)}

    first = read_page(client.get("/orders/", wide))
    second = read_page(client.get("/orders/", {**wide, "page": 2}))

    assert sum(number(k) in first.text for k in range(1, 61)) == 50
    assert sum(number(k) in second.text for k in range(1, 61)) == 10
    assert "Showing" in first.text and "60" in first.text
    for k in range(51, 55):
        assert "Covered" in second.row_with(number(k))
    assert "Low cover" in second.row_with(number(55))
    for k in range(56, 61):
        assert "Short" in second.row_with(number(k))
