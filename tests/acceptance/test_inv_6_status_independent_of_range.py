"""INV-6: a status depends only on the plant's data and settings, never on the date filter.
Every order shown in a narrow range has the same status as in the wide range."""

from tests.acceptance import builders
from tests.acceptance.support import PLANT, Stock, days, one_component_order, read_page

STATUSES = (builders.SHORT, builders.LOW_COVER, builders.COVERED)


def status_in(row: str) -> str:
    found = [status for status in STATUSES if status in row]
    assert len(found) == 1, row
    return found[0]


def test_inv_6_narrowing_the_range_changes_no_status(fakes, clock, client_as):
    # RM-1: 300 PC shared by orders on days 1, 3, 5, 7, 9 that each need 70.
    numbers = [f"100010{n}" for n in range(1, 6)]
    fakes.sap.orders += [
        one_component_order(number, days(2 * k - 1), "RM-1", "70")
        for k, number in enumerate(numbers, start=1)
    ]
    fakes.sap.stock.append(Stock("RM-1", 300))
    client = client_as("Viewer")

    wide = read_page(client.get("/orders/", {"plant": PLANT, "from": days(0), "to": days(14)}))
    statuses = {number: status_in(wide.row_with(number)) for number in numbers}
    for start, end in [(days(3), days(9)), (days(5), days(5)), (days(7), days(14))]:
        narrow = read_page(client.get("/orders/", {"plant": PLANT, "from": start, "to": end}))
        for number in numbers:
            if narrow.has_row_with(number):
                assert status_in(narrow.row_with(number)) == statuses[number], (number, start)

    assert set(statuses.values()) >= {builders.COVERED, builders.SHORT}
