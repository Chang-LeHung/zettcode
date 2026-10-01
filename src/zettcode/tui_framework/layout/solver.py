"""Constraint arithmetic shared by the layout containers."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

TrackSize = int | Callable[[int], int] | None


@dataclass(frozen=True, slots=True)
class Track:
    """One row or column in a box layout.

    Attributes:
        size: Fixed cells, a callable receiving the available cells, or ``None``
            to leave the track at its minimum.
        flex: Share of the leftover space; zero never grows.
        minimum: Floor applied to the final extent.
    """

    size: TrackSize = None
    flex: int = 0
    minimum: int = 0

    def fixed(self, available: int) -> int:
        """Return the extent this track claims before flex is shared out.

        Args:
            available: Cells the box has on the main axis, passed on to a
                callable ``size``.
        """
        if callable(self.size):
            return max(self.minimum, self.size(available))
        if self.size is None:
            return self.minimum
        return max(self.minimum, self.size)


def resolve_tracks(available: int, tracks: Sequence[Track]) -> list[int]:
    """Return the extent of every track, honoring fixed, minimum, and flex.

    Fixed tracks keep their size and flex tracks share whatever is left. When
    the fixed sizes alone overflow the space, every track is scaled down
    proportionally so a box never paints outside its own rectangle.

    Args:
        available: Cells the box has on the main axis.
        tracks: Per-slot sizing requests, in layout order.
    """
    available = max(0, available)
    if not tracks:
        return []
    fixed = [track.fixed(available) for track in tracks]
    if sum(fixed) > available:
        return _shrink(fixed, available)
    remaining = available - sum(fixed)
    flex_total = sum(max(0, track.flex) for track in tracks)
    if remaining and flex_total:
        extra = [remaining * max(0, track.flex) // flex_total for track in tracks]
        leftover = remaining - sum(extra)
        for index, track in enumerate(tracks):
            if leftover <= 0:
                break
            if track.flex > 0:
                extra[index] += 1
                leftover -= 1
        fixed = [size + bonus for size, bonus in zip(fixed, extra, strict=True)]
    return fixed


def _shrink(sizes: list[int], available: int) -> list[int]:
    """Scale a budget down to fit, handing the rounding remainder forward."""
    total = sum(sizes)
    if total <= available or total == 0:
        return sizes
    scaled = [size * available // total for size in sizes]
    leftover = available - sum(scaled)
    index = 0
    while leftover > 0 and scaled:
        scaled[index % len(scaled)] += 1
        leftover -= 1
        index += 1
    return scaled
