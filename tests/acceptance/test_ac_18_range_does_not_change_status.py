"""AC-18 (REQ-4 / INV-6): narrowing the date range never changes any status shown.

Constructed data (spec.md, "Proven by unit tests only"). Order 1000101 (4 Nov) takes 60 of the
100 PC of RM-1 first, so order 1000102 (8 Nov) is Short. With the range narrowed to start
on 8 Nov, 1000101 is not listed, but 1000102 must still be Short.
"""

from tests.acceptance.support import PLANT, Stock, days, one_component_order, read_page


def test_ac_18_same_order_same_status_in_two_ranges(fakes, clock, client_as):
    fakes.sap.orders += [
        one_component_order("1000101", days(1), "RM-1", "60"),
        one_component_order("1000102", days(5), "RM-1", "60"),
    ]
    fakes.sap.stock.append(Stock("RM-1", 100))
    client = client_as("Viewer")

    wide = read_page(client.get("/orders/", {"plant": PLANT, "from": days(0), "to": days(14)}))
    narrow = read_page(client.get("/orders/", {"plant": PLANT, "from": days(5), "to": days(6)}))

    assert "1000101" not in narrow.text
    assert "Short" in wide.row_with("1000102")
    assert "Short" in narrow.row_with("1000102")
