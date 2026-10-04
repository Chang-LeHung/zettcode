"""The retained widget contract every framework component implements."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from ..render import Canvas
from .events import AnyEvent
from .geometry import Constraints, Point, Rect, Size
from .host import Host
from .theme import DARK, Theme

if TYPE_CHECKING:
    from .app import TuiApp


class Widget:
    """Base class for the retained widget tree.

    Subclasses override the small contract below while the framework owns
    layout order, event delivery, and painting. Nothing in this module knows
    about the coding agent; a widget only reacts to input and draws cells.
    """

    def __init__(self) -> None:
        """Start detached, unfocused, and due for a first measure and paint."""
        self.rect = Rect(0, 0, 0, 0)
        self.parent: Widget | None = None
        self.app: TuiApp | None = None
        self.focused = False
        self._mounted = False
        self._needs_layout = True
        self._needs_paint = True

    @property
    def theme(self) -> Theme:
        """Return the active theme, or the default before this tree is mounted."""
        return self.app.theme if self.app is not None else DARK

    @property
    def focusable(self) -> bool:
        """Return whether Tab traversal may land on this widget."""
        return False

    @property
    def selects_text(self) -> bool:
        """Return whether a drag over this widget selects its own text.

        A widget that does not — a list, a panel, the header — hands the drag
        to the application's screen selection instead, which copies the cells
        the frame actually paints.
        """
        return False

    # -- tree ---------------------------------------------------------------
    @property
    def children(self) -> Sequence[Widget]:
        """Return the child widgets in paint order, if this widget has any."""
        return ()

    def mount(self) -> None:
        """Attach this subtree and run mount hooks exactly once."""
        if self._mounted:
            return
        self._mounted = True
        for child in self.children:
            child.parent = self
            child.mount()
        self.on_mount()

    def unmount(self) -> None:
        """Detach this subtree and run unmount hooks exactly once."""
        if not self._mounted:
            return
        for child in self.children:
            child.unmount()
        self.on_unmount()
        self._mounted = False

    # -- contract -----------------------------------------------------------
    def measure(self, constraints: Constraints) -> Size:
        """Return the size this widget wants within the given constraints.

        Args:
            constraints: Size range the parent allows; a result outside it is
                clamped by ``Constraints.constrain`` in the caller.
        """
        return constraints.constrain(Size(0, 0))

    def layout(self, rect: Rect) -> None:
        """Assign the final rectangle, notifying the widget when it changed.

        Args:
            rect: Absolute cell rectangle; children receive rectangles derived
                from it, so a widget must not assume its own position is (0, 0).
        """
        changed = rect != self.rect
        self.rect = rect
        self._needs_layout = False
        self._needs_paint = True
        if changed:
            self.on_resize(rect)

    def render(self, canvas: Canvas) -> None:
        """Paint this widget into the shared canvas.

        Args:
            canvas: Frame buffer shared by every screen; drawing outside
                ``self.rect`` is allowed but clipped to the canvas.
        """

    def handle(self, event: AnyEvent, host: Host) -> bool:
        """React to one input event and return whether it was consumed.

        Args:
            event: The event routed to this widget, already past the capture phase.
            host: Services such as focus and repaint; a widget never reaches for
                the app directly.
        """
        return False

    def capture_event(self, event: AnyEvent, host: Host) -> bool:
        """React during the root-to-target phase, before the target runs.

        Args:
            event: The event travelling down the tree.
            host: Services such as focus and repaint.
        """
        return False

    def bubble_event(self, event: AnyEvent, host: Host) -> bool:
        """React during the target-to-root phase, after the target declines.

        Args:
            event: The event travelling back up the tree.
            host: Services such as focus and repaint.
        """
        return False

    def cursor(self) -> Point | None:
        """Return the terminal cursor this widget wants, if any."""
        return None

    # -- lifecycle hooks ----------------------------------------------------
    def on_mount(self) -> None:
        """Run once after the subtree is attached."""

    def on_unmount(self) -> None:
        """Run once before the subtree is detached."""

    def on_resize(self, rect: Rect) -> None:
        """Run after the assigned rectangle actually changed."""

    def on_focus(self) -> None:
        """Run when this widget becomes the focus target."""

    def on_blur(self) -> None:
        """Run when this widget stops being the focus target."""

    def on_tick(self) -> None:
        """Run before each frame so a widget can react to the clock."""

    # -- invalidation -------------------------------------------------------
    def invalidate(self) -> None:
        """Mark this widget as needing a repaint on the next frame."""
        self._needs_paint = True

    def request_layout(self) -> None:
        """Mark this widget as needing a fresh measure and repaint."""
        self._needs_layout = True
        self._needs_paint = True

    @property
    def needs_layout(self) -> bool:
        """Return whether the next frame must measure this widget again."""
        return self._needs_layout

    @property
    def needs_paint(self) -> bool:
        """Return whether the next frame must repaint this widget."""
        return self._needs_paint

    def clear_dirty(self) -> None:
        """Record that the current frame already satisfied the dirty flags."""
        self._needs_layout = False
        self._needs_paint = False
