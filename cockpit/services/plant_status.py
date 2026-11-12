"""The statuses of one plant, calculated from its stored snapshot (#27, shared).

Reads the snapshot that the sync (#24) wrote, maps it into the plain input types of
`shortage.calculate` (#20) and calculates with the current cover buffer. The order list, the
order detail, requisitions and the dashboard all use this, so every screen shows the same
statuses (INV-6). Read only.
"""

from datetime import date

from cockpit.models import ProductionOrder, Stock
from cockpit.services.buffer import current_buffer
from cockpit.services.shortage import (
    ComponentLine,
    OrderLine,
    PlantResult,
    ShortageSettings,
    StockLine,
    calculate,
)


def plant_result(plant: str, today: date) -> PlantResult:
    """Calculate the statuses of all active orders of a plant from its snapshot.

    All active orders are passed, whatever date range a screen shows, because an order's
    status depends on the orders that start before it (INV-6).
    """
    orders = ProductionOrder.objects.filter(plant=plant, is_active=True).prefetch_related(
        "components"
    )
    order_lines = [
        OrderLine(
            number=order.number,
            start_date=order.start_date,
            components=tuple(
                ComponentLine(
                    item=component.item,
                    material=component.material,
                    required=component.required_quantity,
                    withdrawn=component.withdrawn_quantity,
                    unit=component.unit,
                )
                for component in order.components.all()
            ),
        )
        for order in orders
    ]
    stock_lines = [
        StockLine(material=row.material, quantity=row.quantity, unit=row.unit)
        for row in Stock.objects.filter(plant=plant)
    ]
    settings = ShortageSettings(buffer_percent=current_buffer())
    return calculate(order_lines, stock_lines, settings, today)
