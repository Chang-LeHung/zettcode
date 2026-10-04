"""A transient notice that expires on the application clock."""

from __future__ import annotations

from collections.abc import Callable
from time import monotonic

from ...tui import RULE
from ..core.focus import walk
from ..core.geometry import Constraints, Size
from ..core.widget import Widget
from ..render import Canvas, Style, truncate
from ..render.text import display_width

LEVELS = ("info", "success", "warning", "error")


class Toast(Widget):
    """A framed notice that counts down while the application keeps painting.

    Shape::

        +-----------------------+
        | saved to disk         |  <- frame and text in the level's colour
        +-----------------------+

    Mount registers a scheduler token so the frame loop keeps running for the
    countdown; ``on_tick`` dismisses it once the deadline passes, either by
    popping its own screen or by calling ``on_expire``.
    """

    def __init__(
        self,
        message: str,
        *,
        level: str = "info",
        duration: float = 3.0,
        clock=monotonic,
        on_expire: Callable[[], None] | None = None,
    ) -> None:
        """Configure the message, the level, the countdown, and the expiry hook.

        Args:
            message: Single line of text; truncated to the toast width.
            level: Colour key, one of ``LEVELS``.
            duration: Seconds the toast stays up, floored at zero.
            clock: Time source for the countdown, injectable for tests.
            on_expire: Called once the countdown ends, instead of the toast
                popping its own screen. The toast then stays mounted until the
                owner removes it.
        """
        super().__init__()
        if level not in LEVELS:
            raise ValueError(f"Unknown toast level: {level!r}")
        self.message = message
        self.level = level
        self.duration = max(0.0, duration)
        self.clock = clock
        self.on_expire = on_expire
        self._token = f"toast:{id(self)}"
        self._deadline = 0.0

    @property
    def remaining(self) -> float:
        """Return the seconds left before the toast expires."""
        return max(0.0, self._deadline - self.clock())

    @property
    def expired(self) -> bool:
        """Return whether the countdown has run out."""
        return self.clock() >= self._deadline

    def on_mount(self) -> None:
        """Start the countdown and keep the frame loop alive while it runs."""
        self._deadline = self.clock() + self.duration
        if self.app is not None:
            self.app.scheduler.animate(self._token)

    def on_unmount(self) -> None:
        """Release the animation token when the toast is removed."""
        if self.app is not None:
            self.app.scheduler.animate(self._token, active=False)

    def on_tick(self) -> None:
        """Dismiss once the countdown reaches zero."""
        if not self.expired:
            return
        if self.on_expire is not None:
            self.on_expire()
            return
        if self.app is not None and any(widget is self for widget in walk(self.app.screens.top.widget)):
            self.app.pop_screen()

    def measure(self, constraints: Constraints) -> Size:
        """Ask for the frame plus one row of message."""
        return constraints.constrain(Size(display_width(self.message) + 4, 3))

    def render(self, canvas: Canvas) -> None:
        """Paint the frame and the message in the level's colour."""
        if self.rect.empty:
            return
        theme = self.theme
        # Clear to the page colour rather than to the terminal's default: the
        # toast floats over the shell, so "no style" would punch a hole through
        # whatever palette is active.
        canvas.fill(
            self.rect.x,
            self.rect.y,
            self.rect.width,
            self.rect.height,
            Style(background=theme.background),
            " ",
        )
        color = {
            "info": theme.text,
            "success": theme.accent,
            "warning": theme.warning,
            "error": theme.error,
        }[self.level]
        width = self.rect.width
        rule = RULE * max(0, width - 2)
        canvas.draw_text(self.rect.x, self.rect.y, f"\u250c{rule}\u2510", Style(foreground=color))
        canvas.draw_text(self.rect.x, self.rect.y + 1, "\u2502", Style(foreground=color))
        canvas.draw_text(
            self.rect.x + 2,
            self.rect.y + 1,
            truncate(self.message, max(0, width - 4)),
            Style(foreground=color, bold=True),
            max_width=max(0, width - 4),
        )
        canvas.draw_text(self.rect.x + width - 1, self.rect.y + 1, "\u2502", Style(foreground=color))
        if self.rect.height > 2:
            canvas.draw_text(self.rect.x, self.rect.y + 2, f"\u2514{rule}\u2518", Style(foreground=color))
