"""Anchored placement of children inside their parent's rectangle."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..core.geometry import Constraints, Rect, Size
from ..core.widget import Widget
from ..render import Canvas

HORIZONTAL = ("start", "center", "end", "stretch")
VERTICAL = ("start", "center", "end", "stretch")


@dataclass(frozen=True, slots=True)
class Anchor:
    """Where a child sits inside its parent's bounds.

    Attributes:
        horizontal: One of ``HORIZONTAL``. ``"stretch"`` fills the parent width,
            ``"center"`` and ``"end"`` offset the child inside the parent, and an
            explicit ``width`` overrides both.
        vertical: One of ``VERTICAL``, with the same meanings on the other axis.
        offset_x: Cells added to the resolved left edge, after alignment.
        offset_y: Cells added to the resolved top edge, after alignment.
        width: Fixed width in cells; ``None`` uses the child's measured width.
            Either way the value is capped to the parent's width.
        height: Fixed height in cells; ``None`` uses the measured height.
    """

    horizontal: str = "start"
    vertical: str = "start"
    offset_x: int = 0
    offset_y: int = 0
    width: int | None = None
    height: int | None = None

    def __post_init__(self) -> None:
        """Reject anchor names the resolver does not know."""
        if self.horizontal not in HORIZONTAL:
            raise ValueError(f"Unknown horizontal anchor: {self.horizontal!r}")
        if self.vertical not in VERTICAL:
            raise ValueError(f"Unknown vertical anchor: {self.vertical!r}")

    def resolve(self, bounds: Rect, measured: Size) -> Rect:
        """Return the child rectangle this anchor picks inside bounds.

        Args:
            bounds: Parent rectangle the child is placed inside.
            measured: Size the child asked for; unused on an axis the anchor
                stretches, and used otherwise when ``width``/``height`` is unset.
                The result is capped to ``bounds`` either way.
        """
        width = self._extent(self.horizontal, bounds.width, measured.width, self.width)
        height = self._extent(self.vertical, bounds.height, measured.height, self.height)
        x = bounds.x + self._offset(self.horizontal, bounds.width, width) + self.offset_x
        y = bounds.y + self._offset(self.vertical, bounds.height, height) + self.offset_y
        return Rect(x, y, max(0, width), max(0, height))

    @staticmethod
    def _extent(axis: str, available: int, measured: int, pinned: int | None) -> int:
        """Return one axis extent, letting an explicit pin beat the anchor.

        Args:
            axis: Anchor name for this axis.
            available: Cells the parent offers on the axis.
            measured: Size the child asked for.
            pinned: Explicit width or height; ``None`` defers to the anchor, and
                a pin is still capped to ``available``.
        """
        if pinned is not None:
            return min(pinned, available)
        if axis == "stretch":
            return available
        return min(measured, available)

    @staticmethod
    def _offset(axis: str, available: int, extent: int) -> int:
        """Return the leading offset for one axis and placement mode."""
        if axis == "center":
            return max(0, (available - extent) // 2)
        if axis == "end":
            return max(0, available - extent)
        return 0


@dataclass(frozen=True, slots=True)
class OverlaySlot:
    """One anchored child.

    Attributes:
        widget: The child to place.
        anchor: Where inside the overlay's rectangle the child goes.
    """

    widget: Widget
    anchor: Anchor = Anchor()


class Overlay(Widget):
    """Stack children on top of each other at anchored positions.

    Shape::

        parent rectangle
        +---------------------------+
        |          +--------+       |
        |          | child  |       |  <- measured, then placed by its anchor
        |          +--------+       |
        +---------------------------+

    Later slots paint over earlier ones. Each child is measured against the full
    rectangle first, so an anchor can align by the child's own size; the result
    is always capped to the parent, and ``"stretch"`` fills it.
    """

    def __init__(self, slots: Sequence[OverlaySlot]) -> None:
        """Store the slots in paint order, so later slots sit on top.

        Args:
            slots: Children to place; each is measured against the full overlay
                rectangle before its anchor resolves the final position.
        """
        super().__init__()
        self.slots = tuple(slots)

    @property
    def children(self) -> tuple[Widget, ...]:
        """Expose the anchored widgets in paint order."""
        return tuple(slot.widget for slot in self.slots)

    def measure(self, constraints: Constraints) -> Size:
        """Report the smallest rectangle that fits every child."""
        widest = 0
        tallest = 0
        for slot in self.slots:
            child = slot.widget.measure(constraints)
            widest = max(widest, child.width)
            tallest = max(tallest, child.height)
        return constraints.constrain(Size(widest, tallest))

    def layout(self, rect: Rect) -> None:
        """Measure each child, then place it at its anchored rectangle."""
        super().layout(rect)
        for slot in self.slots:
            measured = slot.widget.measure(Constraints.loose(rect.size))
            slot.widget.layout(slot.anchor.resolve(rect, measured))

    def render(self, canvas: Canvas) -> None:
        """Paint the children in slot order, so later slots cover earlier ones."""
        for slot in self.slots:
            slot.widget.render(canvas)


def centered(widget: Widget, *, horizontal: str = "center", vertical: str = "center") -> Overlay:
    """Wrap one widget in a full-rect overlay anchored at the given edges.

    Args:
        widget: The single child to place.
        horizontal: Horizontal anchor name, from ``"start"`` to ``"stretch"``.
        vertical: Vertical anchor name, from ``"start"`` to ``"stretch"``.
    """
    return Overlay([OverlaySlot(widget, Anchor(horizontal=horizontal, vertical=vertical))])
