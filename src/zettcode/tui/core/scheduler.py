"""Frame scheduling that keeps animation cost inside a fixed budget."""

from __future__ import annotations

from collections.abc import Callable
from time import monotonic


class Scheduler:
    """Decide when the application should paint its next frame.

    Repaints are requested explicitly, while animations run on a bounded
    interval so a busy widget cannot drive the loop at full speed.
    """

    def __init__(self, *, max_fps: float = 30.0, clock: Callable[[], float] = monotonic) -> None:
        """Configure the frame budget and the clock used to time frames.

        Args:
            max_fps: Ceiling for animated frames per second; must be positive.
            clock: Monotonic time source, injectable so tests can step time.
        """
        if max_fps <= 0:
            raise ValueError("max_fps must be positive")
        self.max_fps = max_fps
        self.interval = 1.0 / max_fps
        self.clock = clock
        self.on_request: Callable[[], None] | None = None
        self._last_frame = float("-inf")
        self._dirty = True
        self._animations: set[str] = set()

    @property
    def animating(self) -> bool:
        """Return whether any animation token is registered."""
        return bool(self._animations)

    @property
    def animations(self) -> tuple[str, ...]:
        """Return the registered animation tokens, sorted."""
        return tuple(sorted(self._animations))

    def request_repaint(self) -> None:
        """Mark the frame as stale even if no animation is running."""
        self._dirty = True
        self._notify()

    def animate(self, token: str, *, active: bool = True) -> None:
        """Register or release one animation token.

        Args:
            token: Stable identity for one animation source, e.g.
                ``f"spinner:{id(self)}"``; registering the same token twice is
                harmless because the set collapses duplicates.
            active: ``True`` keeps the frame loop alive for this token, ``False``
                releases it without disturbing any other animation.
        """
        if not token:
            raise ValueError("Animation token cannot be empty")
        if active:
            self._animations.add(token)
            self._notify()
        else:
            self._animations.discard(token)

    def poll(self, *, now: float | None = None) -> bool:
        """Return whether a frame is due, recording it as painted.

        Args:
            now: Overrides the clock; tests use it to pin the frame time.
        """
        moment = self.clock() if now is None else now
        if not self._dirty:
            if not self._animations or moment - self._last_frame < self.interval:
                return False
        self._dirty = False
        self._last_frame = moment
        return True

    def delay(self, *, now: float | None = None) -> float | None:
        """Return seconds until the next frame, or None when fully idle.

        Args:
            now: Overrides the clock, matching ``poll``.
        """
        moment = self.clock() if now is None else now
        if self._dirty:
            return 0.0
        if not self._animations:
            return None
        return max(0.0, self.interval - (moment - self._last_frame))

    def _notify(self) -> None:
        """Wake a sleeping driver, which would otherwise miss a late request."""
        if self.on_request is not None:
            self.on_request()
