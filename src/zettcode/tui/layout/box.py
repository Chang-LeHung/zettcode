"""Vertical and horizontal box containers."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from ..core.geometry import Constraints, Point, Rect, Size
from ..core.widget import Widget
from ..render import Canvas
from .solver import Track, resolve_tracks


@dataclass(frozen=True, slots=True)
class Slot:
    """One child of a box, with its own sizing policy on the main axis.

    Attributes:
        widget: The child laid out in this slot.
        size: Fixed cell count on the main axis, or a callable receiving the
            box's extent on the cross axis (the width of a ``VBox``, the height
            of an ``HBox``) and returning main-axis cells. ``None`` contributes
            nothing to the fixed budget, leaving the slot to ``flex``.
        flex: Share of the leftover space; zero means the slot never grows.
        min_size: Floor applied to the main-axis extent.
    """

    widget: Widget
    size: int | Callable[[int], int] | None = None
    flex: int = 0
    min_size: int = 0

    def track(self) -> Track:
        """Describe this slot to the track solver on the main axis."""
        return Track(self.size, self.flex, self.min_size)


class _Box(Widget):
    """Shared behavior for the two box directions."""

    def __init__(self, slots: Sequence[Slot]) -> None:
        """Store the slots in paint order."""
        super().__init__()
        self.slots = tuple(slots)

    @property
    def children(self) -> tuple[Widget, ...]:
        """Expose one child per slot."""
        return tuple(slot.widget for slot in self.slots)

    @property
    def _vertical(self) -> bool:
        """Return whether children stack vertically; subclasses decide."""
        raise NotImplementedError

    def render(self, canvas: Canvas) -> None:
        """Paint every child in slot order; the box itself draws nothing."""
        for slot in self.slots:
            slot.widget.render(canvas)

    def cursor(self) -> Point | None:
        """Return the first cursor any child asks for, in slot order."""
        for slot in self.slots:
            cursor = slot.widget.cursor()
            if cursor is not None:
                return cursor
        return None

    def _cross_constraints(self, constraints: Constraints) -> Constraints:
        """Leave the main axis open and bound the cross axis by the parent."""
        if self._vertical:
            return Constraints(0, constraints.max_width, 0, None)
        return Constraints(0, None, 0, constraints.max_height)

    def measure(self, constraints: Constraints) -> Size:
        """Sum the main-axis sizes and take the largest cross-axis child."""
        inner = self._cross_constraints(constraints)
        total = 0
        widest = 0
        tallest = 0
        for slot in self.slots:
            child = slot.widget.measure(inner)
            natural = child.height if self._vertical else child.width
            main = natural if slot.size is None or callable(slot.size) else slot.size
            total += max(slot.min_size, main)
            widest = max(widest, child.width)
            tallest = max(tallest, child.height)
        size = Size(widest, total) if self._vertical else Size(total, tallest)
        return constraints.constrain(size)


class VBox(_Box):
    """Stack children top to bottom, sharing leftover height by flex.

    Shape::

        +-------------------+  <- the box's own rectangle
        | header  (size=1)  |  <- fixed rows keep their height
        +-------------------+
        | body    (flex=1)  |  <- flexible rows share what is left
        |                   |
        +-------------------+
        | status  (size=1)  |
        +-------------------+

    A fixed size may be a callable, which receives the box's *width* — a
    wrapping child's height depends on the space across, not along. When the
    fixed rows alone overflow, every row is scaled down proportionally so the
    box never paints outside its rectangle.
    """

    @property
    def _vertical(self) -> bool:
        """Stack children top to bottom."""
        return True

    def layout(self, rect: Rect) -> None:
        """Split the height across the slots and stack them from the top."""
        super().layout(rect)
        y = rect.y
        measured = resolve_tracks(rect.height, [s.track() for s in self.slots], cross=rect.width)
        for slot, extent in zip(self.slots, measured, strict=True):
            slot.widget.layout(Rect(rect.x, y, rect.width, extent))
            y += extent


class HBox(_Box):
    """Place children left to right, sharing leftover width by flex.

    Shape::

        +--------+---------------------------+
        | left   | right                     |  <- size=8, then flex=1
        +--------+---------------------------+
                  ^ the callable form receives the box's *height*

    The horizontal mirror of `VBox`: same track solver, same proportional
    shrink when the fixed columns do not fit.
    """

    @property
    def _vertical(self) -> bool:
        """Place children left to right."""
        return False

    def layout(self, rect: Rect) -> None:
        """Split the width across the slots and place them from the left."""
        super().layout(rect)
        x = rect.x
        measured = resolve_tracks(rect.width, [s.track() for s in self.slots], cross=rect.height)
        for slot, extent in zip(self.slots, measured, strict=True):
            slot.widget.layout(Rect(x, rect.y, extent, rect.height))
            x += extent
