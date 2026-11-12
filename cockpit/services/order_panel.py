"""What the order detail page shows next to each component and in the requisition panel (#28).

Plain functions: which Requisition cell each component row gets (a Request button, the label
of its latest requisition, or a dash), and the live "Sent to SAP" preview of the panel. The
views only call these and render a template. Nothing here changes data.
In Mendix terms: the microflows behind the Requisition column and the preview of the form.
"""

from dataclasses import dataclass
from decimal import Decimal

from cockpit.models import Requisition
from cockpit.services import requisitions
from cockpit.services.plant_status import DetailRow, OrderDetail
from cockpit.services.shortage import Status

REQUESTABLE = {Status.SHORT, Status.LOW_COVER}


@dataclass(frozen=True)
class RowCell:
    """The Requisition cell of one component row.

    `kind` is "request" (a Request button), "label" (the latest requisition, clickable) or
    "none" (a dash). `requisition` is set for a label.
    """

    kind: str
    requisition: Requisition | None = None


@dataclass(frozen=True)
class TableRow:
    """One component row, its Requisition cell and whether the panel is showing its material."""

    row: DetailRow
    cell: RowCell
    selected: bool


def latest_by_material(order_number: str) -> dict[str, Requisition]:
    """The latest requisition (highest id) of each material of this order."""
    latest: dict[str, Requisition] = {}
    for requisition in Requisition.objects.filter(order__number=order_number).order_by("id"):
        latest[requisition.material] = requisition
    return latest


def table_rows(detail: OrderDetail, can_create: bool, selected_material: str) -> list[TableRow]:
    """The component rows with their Requisition cell (ui-spec 4.2).

    A requisition covers all lines of a material, so each line of that material shows the same
    label. A short or low cover line without any requisition shows Request, but only to a user
    who may create requisitions: others see a dash. Every other line shows a dash.
    """
    latest = latest_by_material(detail.number)
    rows = []
    for row in detail.rows:
        requisition = latest.get(row.material)
        if requisition is not None:
            cell = RowCell("label", requisition)
        elif can_create and row.status in REQUESTABLE:
            cell = RowCell("request")
        else:
            cell = RowCell("none")
        rows.append(
            TableRow(
                row, cell, selected=bool(selected_material) and row.material == selected_material
            )
        )
    return rows


def preview_sent(order_number: str, material: str, raw_quantity: str) -> tuple[Decimal, str] | None:
    """The quantity that would be sent to SAP for what the planner typed, with its unit.

    The units come from the stored order, never from the client. Returns None when the number
    is not valid or the order and material cannot be requested; the form then shows a dash.
    """
    try:
        prefill = requisitions.prepare(order_number, material)
        quantity = requisitions.validate_quantity(raw_quantity)
        sent = requisitions.to_stock_unit(quantity, prefill.unit, prefill.stock_unit)
    except requisitions.RequisitionRefused:
        return None
    return sent, prefill.stock_unit
