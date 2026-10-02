"""The application runtime: screens, focus, routing, layout, and painting."""

from __future__ import annotations

from collections.abc import Callable
from time import monotonic

from ..render import Canvas
from .events import AnyEvent, MouseEvent, ResizeEvent
from .focus import FocusManager, walk
from .geometry import Point, Rect
from .host import Host
from .keymap import CommandRegistry, Keymap
from .scheduler import Scheduler
from .screen import Screen, ScreenStack
from .theme import DARK, Theme
from .widget import Widget


class TuiApp(Host):
    """Own one widget tree and everything that drives it.

    It is the only :class:`~zettcode.tui.core.host.Host`, so widgets
    reach the outside world only through it. It never touches a terminal:
    callers hand it a size and paint the returned canvas, which is what lets
    the same tree run under a real TTY or a headless test.
    """

    def __init__(
        self,
        root: Widget,
        *,
        width: int = 80,
        height: int = 24,
        theme: Theme | None = None,
        clock: Callable[[], float] = monotonic,
        max_fps: float = 30.0,
        keymap: Keymap | None = None,
        commands: CommandRegistry | None = None,
        on_copy: Callable[[str], None] | None = None,
        reduced_motion: bool = False,
    ) -> None:
        """Build an app around ``root`` at the given size, theme, and frame budget.

        Args:
            root: Widget at the base of the tree; it is wrapped in a ``"main"``
                screen, so callers never build that layer themselves.
            width: Initial width in cells, floored at 1; a real terminal
                overwrites it through ``resize``.
            height: Initial height in cells, floored at 1.
            theme: Active palette; defaults to ``DARK``.
            clock: Time source shared with the scheduler and the widgets.
            max_fps: Ceiling for animation frames, enforced by the scheduler.
            keymap: Bindings to use; a fresh empty one is created when omitted.
            commands: Commands the bindings may name; same default as ``keymap``.
            on_copy: Sink that mirrors copied text to the system clipboard.
            reduced_motion: Suppress decorative animation for the whole tree.
        """
        self.root = root
        self.width = max(1, width)
        self.height = max(1, height)
        self.theme = theme or DARK
        self.clock = clock
        self.max_fps = max_fps
        self.keymap = keymap or Keymap()
        self.commands = commands or CommandRegistry()
        self.focus_manager = FocusManager()
        self.scheduler = Scheduler(max_fps=max_fps, clock=clock)
        self.screens = ScreenStack(Screen(root, name="main"))
        self.clipboard = ""
        self.refreshed = False
        self.running = True
        self.reduced_motion = reduced_motion
        self._on_copy = on_copy
        self._layout_dirty = True
        self._mounted = False

    # -- lifecycle ----------------------------------------------------------
    def mount(self) -> None:
        """Attach every screen and give each widget a reference back to the app."""
        if self._mounted:
            return
        for screen in self.screens:
            self._attach(screen.widget)
            screen.widget.mount()
        self._mounted = True
        if self.focus_manager.focused is None:
            candidates = self.focus_manager.focusables(self.screens.top.widget)
            if candidates:
                self.focus_manager.focus(candidates[0])
        self.request_layout()

    def close(self) -> None:
        """Detach every screen, running the unmount hooks once."""
        if not self._mounted:
            return
        for screen in self.screens:
            screen.widget.unmount()
        self._mounted = False

    def _attach(self, widget: Widget) -> None:
        """Give every widget in the subtree a back reference to this app."""
        widget.app = self
        for child in widget.children:
            self._attach(child)

    # -- Host ---------------------------------------------------------------
    def focus(self, widget: Widget | None) -> None:
        """Move focus and repaint, running the blur and focus hooks.

        Args:
            widget: New focus target, or ``None`` to clear focus.
        """
        self.focus_manager.focus(widget)
        self.invalidate()

    def focused_widget(self) -> Widget | None:
        """Return the widget that receives keyboard input, if any."""
        return self.focus_manager.focused

    def invalidate(self) -> None:
        """Request a repaint on the next frame."""
        self.scheduler.request_repaint()

    def request_layout(self) -> None:
        """Mark the geometry stale so the next paint measures the tree again."""
        self._layout_dirty = True
        self.scheduler.request_repaint()

    def copy(self, text: str) -> None:
        """Store text on the clipboard and mirror it to the copy handler.

        Args:
            text: Text to copy; an empty string is ignored so a stray copy never
                wipes the clipboard.
        """
        if not text:
            return
        self.clipboard = text
        if self._on_copy is not None:
            self._on_copy(text)

    def set_copy_handler(self, handler: Callable[[str], None] | None) -> None:
        """Install the sink that mirrors copied text to the system clipboard."""
        self._on_copy = handler

    def refresh(self) -> None:
        """Repaint from scratch, discarding the renderer's previous frame."""
        self.refreshed = True
        self.request_layout()

    def exit(self) -> None:
        """Ask the terminal loop to stop after the current frame."""
        self.running = False
        self.invalidate()

    # -- screens ------------------------------------------------------------
    def push_screen(self, screen: Screen) -> Screen:
        """Stack a layer on top and move focus into it.

        Args:
            screen: Layer to stack; when it holds no focusable widget the layer
                below keeps the keyboard focus.
        """
        self.screens.top.remembered_focus = self.focus_manager.focused
        self.screens.push(screen)
        if self._mounted:
            self._attach(screen.widget)
            screen.widget.mount()
        candidates = self.focus_manager.focusables(screen.widget)
        if candidates:
            # A screen without focusable widgets (a toast, a hint) must not steal
            # focus from whatever the user was already typing into.
            self.focus_manager.focus(candidates[0])
        self.request_layout()
        return screen

    def pop_screen(self) -> Screen | None:
        """Remove the topmost layer and restore the focus it covered."""
        screen = self.screens.pop()
        if screen is None:
            return None
        if self._mounted:
            screen.widget.unmount()
        restored = self.screens.top
        self.focus_manager.focus(restored.remembered_focus or self.focus_manager.first(restored.widget))
        self.request_layout()
        return screen

    def focus_next(self, direction: int = 1) -> Widget | None:
        """Move focus to the next or previous Tab stop in the active scope.

        Args:
            direction: Positive moves forward, negative moves backward; the
                scope is the top screen, so a modal layer traps Tab.
        """
        widget = self.focus_manager.move(self.screens.top.widget, direction)
        self.invalidate()
        return widget

    # -- geometry -----------------------------------------------------------
    def resize(self, width: int, height: int) -> None:
        """Adopt a new terminal size and re-measure the tree.

        Args:
            width: New width in cells, floored at 1.
            height: New height in cells, floored at 1.
        """
        self.width = max(1, width)
        self.height = max(1, height)
        self.request_layout()

    def layout(self) -> None:
        """Assign rectangles for every screen at the current size."""
        self._ensure_mounted()
        rect = Rect(0, 0, self.width, self.height)
        for screen in self.screens:
            screen.widget.layout(rect)
        self._layout_dirty = False

    def render(self) -> Canvas:
        """Paint every screen in order into one fresh canvas."""
        if self._layout_dirty:
            self.layout()
        canvas = Canvas(self.width, self.height)
        for screen in self.screens:
            screen.widget.render(canvas)
        return canvas

    def cursor(self) -> Point | None:
        """Return the cursor the focused widget wants, if any."""
        focused = self.focus_manager.focused
        if focused is not None:
            return focused.cursor()
        return self.screens.top.widget.cursor()

    def tick(self) -> None:
        """Give every mounted widget a chance to react to the clock."""
        for screen in list(self.screens):
            for widget in walk(screen.widget):
                widget.on_tick()

    # -- input --------------------------------------------------------------
    def dispatch(self, event: AnyEvent) -> bool:
        """Route one event through capture, keymap, target, and bubble phases.

        Args:
            event: Input to route; a resize is applied directly instead of being
                delivered to the tree.

        Returns:
            Whether some widget or binding consumed the event.
        """
        if self._layout_dirty:
            self.layout()
        if isinstance(event, ResizeEvent):
            self.resize(event.width or self.width, event.height or self.height)
            return True

        target = self._target(event)
        if target is None:
            return False
        path = self._path(target)

        for widget in path:
            if widget.capture_event(event, self):
                self.invalidate()
                return True

        if self._run_binding(event, "capture"):
            return True

        if target.handle(event, self):
            self.invalidate()
            return True

        if self._run_binding(event, "bubble"):
            return True

        for widget in reversed(path[:-1]):
            if widget.bubble_event(event, self):
                self.invalidate()
                return True
        return False

    def _run_binding(self, event: AnyEvent, priority: str) -> bool:
        """Run the command bound to this event at one priority, if any."""
        command = self.keymap.resolve(event, priority=priority)
        if command is None or not self.commands.run(command, event, self):
            return False
        self.invalidate()
        return True

    def _routable(self) -> list[Screen]:
        """Return screens that may receive input, topmost first."""
        screens = list(self.screens)
        for index in range(len(screens) - 1, -1, -1):
            if screens[index].modal:
                screens = screens[index:]
                break
        return list(reversed(screens))

    def _target(self, event: AnyEvent) -> Widget | None:
        """Return the widget an event is addressed to before any bubbling."""
        if isinstance(event, MouseEvent):
            return self._hit(event.x, event.y)
        focused = self.focus_manager.focused
        return focused if focused is not None else self.screens.top.widget

    def _hit(self, x: int, y: int) -> Widget:
        """Return the topmost widget under one cell, skipping covered screens."""
        routable = self._routable()
        for screen in routable:
            hit = _hit_test(screen.widget, x, y)
            if hit is not None:
                return hit
        return routable[0].widget

    @staticmethod
    def _path(widget: Widget) -> list[Widget]:
        """Return the root-to-widget chain used for capture and bubble phases."""
        path: list[Widget] = []
        node: Widget | None = widget
        while node is not None:
            path.append(node)
            node = node.parent
        path.reverse()
        return path

    def _ensure_mounted(self) -> None:
        """Mount the tree on first use so callers need not mount it themselves."""
        if not self._mounted:
            self.mount()


def _hit_test(widget: Widget, x: int, y: int) -> Widget | None:
    """Return the deepest widget containing one cell, searching paint order."""
    if not widget.rect.contains(x, y):
        return None
    for child in reversed(widget.children):
        hit = _hit_test(child, x, y)
        if hit is not None:
            return hit
    return widget
