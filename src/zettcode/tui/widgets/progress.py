"""Transient activity widgets: a spinner and a determinate bar."""

from __future__ import annotations

from collections.abc import Sequence
from time import monotonic

from ..core.geometry import Constraints, Size
from ..core.widget import Widget
from ..render import Canvas, Style
from ..render.text import display_width, truncate

DEFAULT_FRAMES = ("\u280b", "\u2819", "\u2839", "\u2838", "\u283c", "\u2834", "\u2826", "\u2827", "\u2807", "\u280f")


class Spinner(Widget):
    """An animated glyph that keeps the frame loop alive while it runs.

    Shape::

        <glyph> working                   <- braille frames, cycled every interval

    The glyph is derived from the clock at paint time rather than advanced by a
    tick, so it never drifts or speeds up when frames are dropped. What keeps
    frames coming is the scheduler token registered in ``start``; with
    ``app.reduced_motion`` the token is skipped and the first frame stays put.
    """

    def __init__(
        self,
        label: str = "",
        *,
        frames: Sequence[str] = DEFAULT_FRAMES,
        interval: float = 0.12,
        clock=monotonic,
    ) -> None:
        """Configure the glyph cycle, the interval between frames, and the label.

        Args:
            label: Text drawn after the glyph; omit it for a bare spinner.
            frames: Glyphs cycled in order; an empty sequence falls back to
                ``DEFAULT_FRAMES``.
            interval: Seconds each glyph is held, floored at 0.01.
            clock: Time source, injectable so tests can step the animation.
        """
        super().__init__()
        self.label = label
        self.frames = tuple(frames) or DEFAULT_FRAMES
        self.interval = max(0.01, interval)
        self.clock = clock
        self._started = 0.0
        self._active = False
        self._token = f"spinner:{id(self)}"

    @property
    def active(self) -> bool:
        """Return whether the spinner is registered for animation."""
        return self._active

    def start(self) -> None:
        """Start animating, unless reduced motion is in effect."""
        self._active = True
        self._started = self.clock()
        if self.app is not None and not self.app.reduced_motion:
            self.app.scheduler.animate(self._token)

    def stop(self) -> None:
        """Stop animating and release the scheduler token."""
        self._active = False
        if self.app is not None:
            self.app.scheduler.animate(self._token, active=False)

    def on_mount(self) -> None:
        """Resume the animation when an already running spinner is mounted."""
        if self._active:
            self.start()

    def on_unmount(self) -> None:
        """Release the token so a detached spinner stops costing frames."""
        self.stop()

    @property
    def frame(self) -> str:
        """Return the glyph for the current time, or the first frame when idle."""
        if not self._active or (self.app is not None and self.app.reduced_motion):
            return self.frames[0]
        step = int((self.clock() - self._started) / self.interval)
        return self.frames[step % len(self.frames)]

    def measure(self, constraints: Constraints) -> Size:
        """Ask for one row and the glyph plus label."""
        return constraints.constrain(Size(1 + (1 + display_width(self.label) if self.label else 0), 1))

    def render(self, canvas: Canvas) -> None:
        """Paint the current glyph and label."""
        if self.rect.empty:
            return
        theme = self.theme
        text = f"{self.frame} {self.label}" if self.label else self.frame
        canvas.draw_text(
            self.rect.x,
            self.rect.y,
            truncate(text, self.rect.width),
            Style(foreground=theme.accent, bold=True),
            max_width=self.rect.width,
        )


class ProgressBar(Widget):
    """A determinate bar with an optional label.

    Shape::

        build ##########------------      <- label, filled, empty
              |<-- width * value -->|

    ``value`` is clamped into 0..1; filled cells use U+2588 and empty ones
    U+2591. The label is truncated first and always keeps one cell for the bar;
    if nothing is left, only the label is drawn.
    """

    def __init__(self, value: float = 0.0, *, label: str = "", filled: str = "\u2588", empty: str = "\u2591") -> None:
        """Store the value and the glyphs used for the filled and empty parts.

        Args:
            value: Completion ratio; clamped into ``0.0..1.0`` at paint time.
            label: Text drawn before the bar, followed by one space.
            filled: Glyph repeated for the completed portion of the bar.
            empty: Glyph repeated for the remaining portion.
        """
        super().__init__()
        self.value = value
        self.label = label
        self.filled = filled
        self.empty = empty

    def measure(self, constraints: Constraints) -> Size:
        """Ask for one row and the label plus one cell of bar."""
        return constraints.constrain(Size(1 + display_width(self.label) + (1 if self.label else 0), 1))

    def render(self, canvas: Canvas) -> None:
        """Paint the label and the bar, clamping the value into 0..1."""
        if self.rect.empty:
            return
        theme = self.theme
        width = self.rect.width
        prefix = ""
        if self.label:
            prefix = truncate(f"{self.label} ", max(0, width - 1))
            width -= display_width(prefix)
        if width <= 0:
            canvas.draw_text(self.rect.x, self.rect.y, prefix, Style(foreground=theme.text), max_width=self.rect.width)
            return
        ratio = min(1.0, max(0.0, self.value))
        filled = min(width, int(round(width * ratio)))
        canvas.draw_text(self.rect.x, self.rect.y, prefix, Style(foreground=theme.text), max_width=self.rect.width)
        x = self.rect.x + display_width(prefix)
        canvas.draw_text(x, self.rect.y, self.filled * filled, Style(foreground=theme.accent), max_width=filled)
        canvas.draw_text(
            x + filled,
            self.rect.y,
            self.empty * (width - filled),
            Style(foreground=theme.border),
            max_width=width - filled,
        )
