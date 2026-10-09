"""The application runtime: screens, focus, routing, layout, and painting."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from time import monotonic

from ..render import Canvas, Style
from .events import AnyEvent, MouseAction, MouseEvent, ResizeEvent
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
        title: str | Callable[[], str] = "",
        auto_theme: bool = False,
        clock: Callable[[], float] = monotonic,
        max_fps: float = 120.0,
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
            title: Text the terminal shows in its window or tab name; a callable
                is read once per frame, so a title that changes with the session
                needs no extra plumbing
            auto_theme: Let the runner replace the palette with the one the
                terminal's own background asks for, once it can ask
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
        self._theme = theme or DARK
        self.title = title
        self.auto_theme = auto_theme
        self.clock = clock
        self.max_fps = max_fps
        self.keymap = keymap or Keymap()
        self.commands = commands or CommandRegistry()
        self.focus_manager = FocusManager()
        self.scheduler = Scheduler(max_fps=max_fps, clock=clock)
        self._main = Screen(root, name="main")
        self.screens = ScreenStack(self._main)
        self.clipboard = ""
        self.refreshed = False
        self.running = True
        self.reduced_motion = reduced_motion
        self._on_copy = on_copy
        self._mouse_capture: Widget | None = None
        self._frame: Canvas | None = None
        self._select_anchor: tuple[int, int] | None = None
        self._select_head: tuple[int, int] | None = None
        self._layout_dirty = True
        self._mounted = False

    @property
    def theme(self) -> Theme:
        """Return the palette every widget reads while painting."""
        return self._theme

    @theme.setter
    def theme(self, value: Theme) -> None:
        """Adopt a new palette, forcing the next frame to repaint from scratch.

        Widgets read ``theme`` at paint time, but their caches and the
        differential renderer may still hold the previous colours; dropping the
        previous frame is what guarantees a switch cannot leave half the screen
        in the old palette.
        """
        if value == self._theme:
            return
        self._theme = value
        self.refreshed = True
        self.scheduler.request_repaint()

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

    def set_root(self, root: Widget) -> None:
        """Replace the base widget, mounting the new tree where the old one stood.

        A shell can put something cheap up first — the composer, while the
        application's own modules are still loading — and then hand this running
        app the real tree. Focus moves into the new tree and every cell is
        repainted, so a swap cannot leave a mixture of the two on screen.

        Args:
            root: Widget to install as the base of the ``"main"`` screen.
        """
        previous = self._main.widget
        self.root = root
        self._main.widget = root
        if not self._mounted:
            return
        self._attach(root)
        root.mount()
        if previous is not None:
            previous.unmount()
        candidates = self.focus_manager.focusables(root)
        self.focus_manager.focus(candidates[0] if candidates else None)
        self.refresh()

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

    @property
    def layout_pending(self) -> bool:
        """Return whether the next frame must re-measure the widget tree."""
        return self._layout_dirty

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
        """Paint every screen in order into one fresh canvas.

        The canvas starts filled with the palette's page colour when it names
        one, because a light palette has to paint its own page: the terminal's
        background is somebody else's dark. A palette with no page colour —
        the dark one — leaves those cells to the terminal, so only the widgets
        that draw a surface of their own change what is underneath.
        """
        if self._layout_dirty:
            self.layout()
        canvas = Canvas(self.width, self.height)
        if self.theme.background is not None:
            canvas.fill(0, 0, self.width, self.height, Style(background=self.theme.background))
        for screen in self.screens:
            screen.widget.render(canvas)
        self._frame = canvas
        self._paint_selection(canvas)
        return canvas

    def _paint_selection(self, canvas: Canvas) -> None:
        """Mark the cells a screen selection covers, leaving their glyphs alone."""
        if self._select_anchor is None or self._select_head is None:
            return
        (first_x, first_y), (last_x, last_y) = sorted((self._select_anchor, self._select_head))
        for y in range(first_y, last_y + 1):
            left = first_x if y == first_y else 0
            right = last_x if y == last_y else canvas.width
            if right > left:
                canvas.restyle(left, y, right - left, _invert)

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

        if isinstance(event, MouseEvent):
            self._track_mouse(event, target)
            self._track_selection(event, path)

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

    def _track_mouse(self, event: MouseEvent, target: Widget) -> None:
        """Keep a drag with the widget that started it, until the button is up.

        A pointer that leaves the widget mid-drag — over the composer, past the
        edge of a list — would otherwise hand every later movement, and the
        release, to whatever is under it: the drag stops extending and the copy
        that happens on release never runs. The press names the owner and the
        release ends it.
        """
        if event.action is MouseAction.DOWN:
            self._mouse_capture = target
        elif event.action is MouseAction.UP:
            self._mouse_capture = None

    def _track_selection(self, event: MouseEvent, path: list[Widget]) -> None:
        """Select the painted frame when a drag starts on text no widget owns.

        Panels, the header, and the status line draw text without modelling it,
        so the frame is the source: the drag marks cells, and the characters
        they hold are copied on release. A widget that selects its own text —
        the transcript — keeps the drag and this stays out of the way.
        """
        if event.action is MouseAction.DOWN:
            if any(widget.selects_text for widget in path):
                self._select_anchor = None
                self._select_head = None
            else:
                self._select_anchor = (event.x, event.y)
                self._select_head = (event.x, event.y)
        elif event.action is MouseAction.MOVE and self._select_anchor is not None:
            self._select_head = self._clamp_to_screen(event.x, event.y)
            # The mark has to follow the pointer; nothing else will ask for a
            # frame while the button is held.
            self.invalidate()
        elif event.action is MouseAction.UP and self._select_anchor is not None:
            selected = self.screen_selection_text()
            if selected:
                self.copy(selected)
                # The mark stays, the way a terminal keeps its selection: it is
                # the only sign of what was just copied, and Ctrl-C clears it.
                self.invalidate()

    def _clamp_to_screen(self, x: int, y: int) -> tuple[int, int]:
        """Return one cell of the frame, however far outside the pointer went."""
        return min(max(0, x), self.width - 1), min(max(0, y), self.height - 1)

    def screen_selection_text(self) -> str:
        """Return the frame text the current drag covers, or an empty string."""
        frame = self._frame
        if frame is None or self._select_anchor is None or self._select_head is None:
            return ""
        (first_x, first_y), (last_x, last_y) = sorted((self._select_anchor, self._select_head))
        rows: list[str] = []
        for y in range(first_y, last_y + 1):
            left = first_x if y == first_y else 0
            # The head cell is the one under the pointer, and a selection names
            # the text it was dragged over, so the row ends before it.
            right = last_x if y == last_y else frame.width
            rows.append(_frame_row(frame, y, left, right).rstrip())
        while rows and not rows[0]:
            rows.pop(0)
        while rows and not rows[-1]:
            rows.pop()
        return "\n".join(rows)

    def clear_screen_selection(self) -> None:
        """Drop the frame selection and repaint without its mark."""
        if self._select_anchor is None and self._select_head is None:
            return
        self._select_anchor = None
        self._select_head = None
        self.invalidate()

    def _run_binding(self, event: AnyEvent, priority: str) -> bool:
        """Run the command bound to this event at one priority, if any."""
        command = self.keymap.resolve(event, priority=priority)
        if command is None or not self.commands.run(command, event, self):
            return False
        self.invalidate()
        return True

    def _routable(self) -> list[Screen]:
        """Return screens that may receive input, topmost first.

        Paint-only layers are skipped, so a toast drawn over the shell never
        swallows a wheel notch or a keystroke meant for what is underneath.
        """
        screens = [screen for screen in self.screens if screen.interactive]
        for index in range(len(screens) - 1, -1, -1):
            if screens[index].modal:
                screens = screens[index:]
                break
        return list(reversed(screens))

    def _target(self, event: AnyEvent) -> Widget | None:
        """Return the widget an event is addressed to before any bubbling."""
        if isinstance(event, MouseEvent):
            if event.action in (MouseAction.MOVE, MouseAction.UP):
                captured = self._captured_widget()
                if captured is not None:
                    return captured
            return self._hit(event.x, event.y)
        focused = self.focus_manager.focused
        return focused if focused is not None else self.screens.top.widget

    def _captured_widget(self) -> Widget | None:
        """Return the widget holding the mouse, dropping it once its screen is gone."""
        widget = self._mouse_capture
        if widget is None:
            return None
        if any(_holds(screen.widget, widget) for screen in self._routable()):
            return widget
        self._mouse_capture = None
        return None

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


def _invert(style: Style) -> Style:
    """Flip reverse video, which is how a selection marks a cell."""
    return replace(style, reverse=not style.reverse)


def _frame_row(frame: Canvas, y: int, left: int, right: int) -> str:
    """Return the characters one frame row holds between two columns."""
    return "".join(cell.character for cell in frame.cells[y][max(0, left) : right])


def _holds(root: Widget, widget: Widget) -> bool:
    """Return whether ``widget`` is ``root`` or one of its descendants."""
    node: Widget | None = widget
    while node is not None:
        if node is root:
            return True
        node = node.parent
    return False


def _hit_test(widget: Widget, x: int, y: int) -> Widget | None:
    """Return the deepest widget containing one cell, searching paint order."""
    if not widget.rect.contains(x, y):
        return None
    for child in reversed(widget.children):
        hit = _hit_test(child, x, y)
        if hit is not None:
            return hit
    return widget
