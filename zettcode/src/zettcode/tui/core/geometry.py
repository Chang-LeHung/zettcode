"""Geometry primitives shared by layout and widgets."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Point:
    """One absolute terminal coordinate measured in cells."""

    x: int = 0
    y: int = 0


@dataclass(frozen=True, slots=True)
class Size:
    """A width and height measured in terminal cells."""

    width: int = 0
    height: int = 0

    @property
    def area(self) -> int:
        """Return the number of cells, treating a negative extent as empty."""
        return max(0, self.width) * max(0, self.height)


@dataclass(frozen=True, slots=True)
class EdgeInsets:
    """Spacing applied to the four sides of a rectangle."""

    top: int = 0
    right: int = 0
    bottom: int = 0
    left: int = 0

    @classmethod
    def all(cls, value: int = 0) -> EdgeInsets:
        """Return equal spacing on every side.

        Args:
            value: Cells applied to top, right, bottom, and left.
        """
        return cls(value, value, value, value)

    @classmethod
    def symmetric(cls, *, vertical: int = 0, horizontal: int = 0) -> EdgeInsets:
        """Return spacing mirrored across both axes.

        Args:
            vertical: Cells for the top and bottom together.
            horizontal: Cells for the left and right together.
        """
        return cls(vertical, horizontal, vertical, horizontal)

    @property
    def vertical(self) -> int:
        """Return the top and bottom spacing combined."""
        return self.top + self.bottom

    @property
    def horizontal(self) -> int:
        """Return the left and right spacing combined."""
        return self.left + self.right


@dataclass(frozen=True, slots=True)
class Rect:
    """An absolute rectangle clamped to the terminal canvas."""

    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        """Return the exclusive right edge."""
        return self.x + self.width

    @property
    def bottom(self) -> int:
        """Return the exclusive bottom edge."""
        return self.y + self.height

    @property
    def size(self) -> Size:
        """Return the rectangle's extent as a Size."""
        return Size(self.width, self.height)

    @property
    def empty(self) -> bool:
        """Return whether the rectangle covers no cells."""
        return self.width <= 0 or self.height <= 0

    def contains(self, x: int, y: int) -> bool:
        """Return whether one cell falls inside this rectangle."""
        return self.x <= x < self.right and self.y <= y < self.bottom

    def inset(self, edges: EdgeInsets | int) -> Rect:
        """Shrink the rectangle by the given spacing, never below empty.

        Args:
            edges: Spacing removed on each side; an int is applied to all four,
                and the result is clamped so width and height never go negative.
        """
        if isinstance(edges, int):
            edges = EdgeInsets.all(edges)
        return Rect(
            self.x + edges.left,
            self.y + edges.top,
            max(0, self.width - edges.horizontal),
            max(0, self.height - edges.vertical),
        )

    def translate(self, dx: int, dy: int) -> Rect:
        """Move the rectangle without resizing it.

        Args:
            dx: Cells to move right; negative moves left.
            dy: Cells to move down; negative moves up.
        """
        return Rect(self.x + dx, self.y + dy, self.width, self.height)

    def intersection(self, other: Rect) -> Rect:
        """Return the overlapping area, or an empty rectangle."""
        x = max(self.x, other.x)
        y = max(self.y, other.y)
        width = max(0, min(self.right, other.right) - x)
        height = max(0, min(self.bottom, other.bottom) - y)
        return Rect(x, y, width, height)

    def union(self, other: Rect) -> Rect:
        """Return the smallest rectangle covering both inputs."""
        if self.empty:
            return other
        if other.empty:
            return self
        x = min(self.x, other.x)
        y = min(self.y, other.y)
        return Rect(x, y, max(self.right, other.right) - x, max(self.bottom, other.bottom) - y)


@dataclass(frozen=True, slots=True)
class Constraints:
    """The size range a widget may choose from during measurement."""

    min_width: int = 0
    max_width: int | None = None
    min_height: int = 0
    max_height: int | None = None

    @classmethod
    def tight(cls, size: Size) -> Constraints:
        """Return constraints that force exactly one size.

        Args:
            size: The only size a child may report.
        """
        return cls(size.width, size.width, size.height, size.height)

    @classmethod
    def loose(cls, size: Size) -> Constraints:
        """Return constraints that allow anything up to one size.

        Args:
            size: Upper bound per axis; both minimums stay at zero.
        """
        return cls(0, size.width, 0, size.height)

    @classmethod
    def unbounded(cls) -> Constraints:
        """Return constraints with no upper bound."""
        return cls()

    def constrain(self, size: Size) -> Size:
        """Clamp a desired size into the allowed range.

        Args:
            size: Size a child asked for; each axis is clamped independently.
        """
        return Size(
            self._clamp(size.width, self.min_width, self.max_width),
            self._clamp(size.height, self.min_height, self.max_height),
        )

    def deflate(self, edges: EdgeInsets) -> Constraints:
        """Remove space reserved for padding from every bound.

        Args:
            edges: Space taken by a padding or border, subtracted from the
                minimum and the maximum on each axis; bounds stop at zero and an
                unbounded maximum stays unbounded.
        """
        return Constraints(
            max(0, self.min_width - edges.horizontal),
            self._shrink(self.max_width, edges.horizontal),
            max(0, self.min_height - edges.vertical),
            self._shrink(self.max_height, edges.vertical),
        )

    @staticmethod
    def _clamp(value: int, minimum: int, maximum: int | None) -> int:
        """Clamp a value into ``minimum..maximum``, where None means unbounded."""
        value = max(value, minimum)
        return value if maximum is None else min(value, max(minimum, maximum))

    @staticmethod
    def _shrink(value: int | None, amount: int) -> int | None:
        """Subtract an amount from an optional upper bound."""
        return None if value is None else max(0, value - amount)
