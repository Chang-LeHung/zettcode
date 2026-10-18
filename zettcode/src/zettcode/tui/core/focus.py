"""Focus ownership and Tab traversal over a widget tree."""

from __future__ import annotations

from collections.abc import Iterator

from .widget import Widget


def walk(widget: Widget) -> Iterator[Widget]:
    """Yield a widget and its descendants in depth-first paint order.

    Args:
        widget: Subtree root; it is yielded before its children.
    """
    yield widget
    for child in widget.children:
        yield from walk(child)


class FocusManager:
    """Track the focused widget and move focus through the tree."""

    def __init__(self) -> None:
        """Start with nothing focused."""
        self._focused: Widget | None = None

    @property
    def focused(self) -> Widget | None:
        """Return the widget that currently owns focus, if any."""
        return self._focused

    def focus(self, widget: Widget | None) -> None:
        """Move focus, running the blur and focus hooks on a real change.

        Args:
            widget: New focus target, or ``None`` to clear focus. Re-focusing the
                current widget is a no-op, so the hooks never fire twice.
        """
        if widget is self._focused:
            return
        previous, self._focused = self._focused, widget
        if previous is not None:
            previous.focused = False
            previous.on_blur()
        if widget is not None:
            widget.focused = True
            widget.on_focus()

    def focusables(self, root: Widget) -> list[Widget]:
        """Return every Tab-reachable widget under root, in traversal order.

        Args:
            root: Subtree to scan; the root itself is included when it opts in
                through ``focusable``.
        """
        return [widget for widget in walk(root) if widget.focusable]

    def first(self, root: Widget) -> Widget | None:
        """Return the first Tab-reachable widget, or the root as a fallback.

        Args:
            root: Subtree to scan.
        """
        candidates = self.focusables(root)
        return candidates[0] if candidates else root

    def move(self, root: Widget, direction: int = 1) -> Widget | None:
        """Move focus by one stop, wrapping at either end.

        Args:
            root: Subtree that defines the Tab scope, usually the top screen.
            direction: Positive moves forward, negative moves backward. When the
                current widget is outside the scope, forward starts at the first
                stop and backward at the last.
        """
        candidates = self.focusables(root)
        if not candidates:
            return None
        if self._focused in candidates:
            index = (candidates.index(self._focused) + direction) % len(candidates)
        else:
            index = 0 if direction > 0 else len(candidates) - 1
        self.focus(candidates[index])
        return candidates[index]
