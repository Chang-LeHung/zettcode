"""Headless driver that feeds input into a TuiApp and snapshots the result.

The harness exists so the framework can be exercised without a real terminal.
It runs a real :class:`TuiApp` at a synthetic size and paints through the same
Canvas and DifferentialRenderer path the terminal runner uses, so a passing
snapshot means the routing and render paths actually ran.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from io import StringIO
from time import monotonic

from ..core.app import TuiApp
from ..core.events import AnyEvent, KeyEvent, MouseAction, MouseEvent, PasteEvent, ResizeEvent, TextEvent
from ..core.geometry import Point
from ..core.theme import Theme
from ..core.widget import Widget
from ..render import Canvas, DifferentialRenderer, Span


@dataclass(frozen=True, slots=True)
class Snapshot:
    """One painted frame: fixed-width text rows plus their styled spans."""

    lines: tuple[str, ...]
    styled: tuple[tuple[Span, ...], ...]
    cursor: Point | None
    width: int
    height: int

    @property
    def text(self) -> str:
        """Return the frame with trailing padding removed, for readable diffs."""
        return "\n".join(line.rstrip() for line in self.lines)


class Harness:
    """Drive a TuiApp with deterministic input and capture its frames."""

    def __init__(
        self,
        root: Widget | None = None,
        *,
        app: TuiApp | None = None,
        width: int = 80,
        height: int = 24,
        clock: Callable[[], float] | None = None,
        theme: Theme | None = None,
    ) -> None:
        """Wrap an existing app, or build one around ``root`` at the given size.

        Args:
            root: Widget to build an app around; mutually exclusive with ``app``.
            app: Existing app to drive, for tests that need to configure it first.
                This harness forwards calls to it instead of owning the tree.
            width: Synthetic width in cells, used only when building an app.
            height: Synthetic height in cells, used only when building an app.
            clock: Time source for the app; defaults to ``monotonic``.
            theme: Palette for the built app; defaults to ``DARK``.
        """
        self.clock = clock or monotonic
        if app is not None:
            self.app = app
            self.root = app.root
        elif root is not None:
            self.root = root
            self.app = TuiApp(root, width=width, height=height, theme=theme, clock=self.clock)
        else:
            raise TypeError("Harness needs a root widget or an existing app")
        self._output = StringIO()
        self._renderer = DifferentialRenderer(self._output)
        self.last_frame = ""
        self.app.mount()

    # -- state the tests read back ------------------------------------------
    #
    # The harness is not the Host: the TuiApp it wraps is. Only the few calls a
    # test actually makes are forwarded, so this class does not grow a second,
    # drifting copy of the TuiApp's surface.
    def focus(self, widget: Widget | None) -> None:
        """Forward a focus change to the app."""
        self.app.focus(widget)

    def focused_widget(self) -> Widget | None:
        """Return the widget that currently owns focus."""
        return self.app.focused_widget()

    @property
    def clipboard(self) -> str:
        """Return the text currently held on the app clipboard."""
        return self.app.clipboard

    @property
    def exited(self) -> bool:
        """Return whether the app has been asked to stop."""
        return not self.app.running

    @property
    def width(self) -> int:
        """Return the synthetic screen width."""
        return self.app.width

    @property
    def height(self) -> int:
        """Return the synthetic screen height."""
        return self.app.height

    # -- input --------------------------------------------------------------
    def press(
        self,
        key: str,
        *,
        shift: bool = False,
        alt: bool = False,
        control: bool = False,
        meta: bool = False,
        repeat: bool = False,
    ) -> bool:
        """Send one named key press.

        Args:
            key: Canonical key name, e.g. ``"enter"`` or ``"ctrl_c"``.
            shift: Shift was held.
            alt: Alt was held.
            control: Ctrl was held.
            meta: Meta was held.
            repeat: Mark the press as an auto-repeat.
        """
        return self.dispatch(KeyEvent(key=key, shift=shift, alt=alt, control=control, meta=meta, repeat=repeat))

    def write(self, text: str) -> bool:
        """Send text one character at a time, as a human typist would."""
        handled = False
        for character in text:
            handled = self.dispatch(TextEvent(text=character)) or handled
        return handled

    def paste(self, text: str) -> bool:
        """Send a whole bracketed-paste payload as a single event."""
        return self.dispatch(PasteEvent(text=text))

    def mouse_down(self, x: int, y: int, *, button: int = 0, shift: bool = False) -> bool:
        """Send a button press at one cell."""
        return self.dispatch(MouseEvent(x=x, y=y, button=button, action=MouseAction.DOWN, shift=shift))

    def mouse_up(self, x: int, y: int, *, button: int = 0, shift: bool = False) -> bool:
        """Send a button release at one cell."""
        return self.dispatch(MouseEvent(x=x, y=y, button=button, action=MouseAction.UP, shift=shift))

    def mouse_move(self, x: int, y: int, *, button: int = 0) -> bool:
        """Send a pointer move, as a drag would produce."""
        return self.dispatch(MouseEvent(x=x, y=y, button=button, action=MouseAction.MOVE))

    def click(self, x: int, y: int, *, button: int = 0) -> bool:
        """Send a press and release at the same cell."""
        return self.mouse_down(x, y, button=button) or self.mouse_up(x, y, button=button)

    def scroll(self, x: int, y: int, *, up: bool = True) -> bool:
        """Send a wheel event at one cell."""
        action = MouseAction.SCROLL_UP if up else MouseAction.SCROLL_DOWN
        return self.dispatch(MouseEvent(x=x, y=y, action=action))

    def resize(self, width: int, height: int) -> None:
        """Change the synthetic screen size and tell the tree about it."""
        self._renderer.reset()
        self.dispatch(ResizeEvent(width=width, height=height))

    def dispatch(self, event: AnyEvent) -> bool:
        """Deliver one event to the tree and report whether it was consumed.

        Args:
            event: Event to deliver, as if it had arrived from the terminal.
        """
        return self.app.dispatch(event)

    # -- rendering ----------------------------------------------------------
    def render(self) -> Snapshot:
        """Layout if needed, paint one frame, and return its snapshot."""
        if self.app.refreshed:
            self.app.refreshed = False
            self._renderer.reset()
        self.app.tick()
        canvas = self.app.render()
        cursor = self.app.cursor()
        self._output.seek(0)
        self._output.truncate(0)
        self._renderer.render(canvas, cursor=None if cursor is None else (cursor.x, cursor.y))
        self.last_frame = self._output.getvalue()
        return _snapshot(canvas, cursor)

    def text(self) -> str:
        """Render and return the trimmed frame text."""
        return self.render().text


def _snapshot(canvas: Canvas, cursor: Point | None) -> Snapshot:
    """Flatten a cell canvas into fixed-width text rows and styled spans."""
    lines: list[str] = []
    styled: list[tuple[Span, ...]] = []
    for row in canvas.cells:
        spans: list[Span] = []
        buffer = ""
        style = None
        for cell in row:
            if cell.continuation:
                continue
            if cell.style != style:
                if buffer:
                    spans.append(Span(buffer, style))
                buffer = ""
                style = cell.style
            buffer += cell.character or " "
        if buffer:
            spans.append(Span(buffer, style))
        styled.append(tuple(spans))
        lines.append("".join(span.text for span in spans))
    return Snapshot(tuple(lines), tuple(styled), cursor, canvas.width, canvas.height)
