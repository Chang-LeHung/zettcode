"""Layers of the application: a widget subtree plus its focus policy."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

from .widget import Widget


@dataclass(slots=True)
class Screen:
    """One stacked layer of the application.

    Attributes:
        widget: Root of this layer's subtree.
        name: Debug label such as ``"approval"``; the base layer is ``"main"``.
        modal: Block input from every layer below this one.
        interactive: Whether the layer may receive input at all. A paint-only
            layer (a toast, a status flash) still draws over the shell but lets
            clicks, wheel, and keys fall through to the layer below.
        remembered_focus: Focus to restore when this layer is uncovered again;
            the app writes it when a new layer is pushed on top.
    """

    widget: Widget
    name: str = ""
    modal: bool = False
    interactive: bool = True
    remembered_focus: Widget | None = field(default=None)


class ScreenStack:
    """The ordered screen layers, oldest first and topmost last."""

    def __init__(self, base: Screen) -> None:
        """Start a stack whose base layer can never be popped.

        Args:
            base: The permanent bottom layer, named ``"main"`` by ``TuiApp``.
        """
        self._screens: list[Screen] = [base]

    def __iter__(self) -> Iterator[Screen]:
        """Iterate from the oldest layer to the newest."""
        return iter(self._screens)

    def __reversed__(self) -> Iterator[Screen]:
        """Iterate from the newest layer to the oldest."""
        return reversed(self._screens)

    def __len__(self) -> int:
        """Return the number of stacked layers."""
        return len(self._screens)

    @property
    def base(self) -> Screen:
        """Return the permanent bottom layer."""
        return self._screens[0]

    @property
    def top(self) -> Screen:
        """Return the layer that currently receives input."""
        return self._screens[-1]

    def push(self, screen: Screen) -> Screen:
        """Add a layer on top and return it.

        Args:
            screen: The new topmost layer; it becomes the only one that can
                receive input until it is popped or a modal layer covers it.
        """
        self._screens.append(screen)
        return screen

    def pop(self) -> Screen | None:
        """Remove the topmost layer, refusing to drop the base screen."""
        if len(self._screens) == 1:
            return None
        return self._screens.pop()
