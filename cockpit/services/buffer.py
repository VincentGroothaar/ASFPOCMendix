"""The cover buffer: the margin above the requirement before a component is Covered (REQ-4).

The buffer is a log of changes (BufferChange); the newest change is the current value.
Saving a new value from the Thresholds screen is the change request (#34).
"""

from decimal import Decimal

from cockpit.models import BufferChange

DEFAULT_BUFFER = Decimal("10")


def last_change() -> BufferChange | None:
    """The newest buffer change, or None when the buffer was never changed."""
    return BufferChange.objects.select_related("changed_by").order_by("-changed_at", "-id").first()


def current_buffer() -> Decimal:
    """The current cover buffer in percent: the newest change, or 10 when there is none."""
    change = last_change()
    return change.value if change else DEFAULT_BUFFER
