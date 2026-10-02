"""Constraint arithmetic shared by the layout containers."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

TrackSize = int | Callable[[int], int] | None


@dataclass(frozen=True, slots=True)
class Track:
    """One row or column in a box layout.

    Attributes:
        size: Fixed cells on the main axis, a callable receiving the box's
            extent on the *cross* axis, or ``None`` to contribute nothing to the
            fixed budget.
        flex: Share of the leftover space; zero never grows.
        minimum: Floor applied to the final extent.
    """

    size: TrackSize = None
    flex: int = 0
    minimum: int = 0

    def fixed(self, available: int, cross: int) -> int:
        """Return the extent this track claims before flex is shared out.

        Args:
            available: Cells the box has on the main axis. Kept for the callers
                that reason in main-axis terms; a callable ``size`` does not see
                it.
            cross: Cells the box has on the other axis, which is what a callable
                ``size`` receives: a child's natural main-axis size usually
                depends on the space it gets across (a paragraph's height
                depends on its width).
        """
        if callable(self.size):
            return max(self.minimum, self.size(cross))
        if self.size is None:
            return self.minimum
        return max(self.minimum, self.size)


def resolve_tracks(available: int, tracks: Sequence[Track], *, cross: int | None = None) -> list[int]:
    """Return the extent of every track, honoring fixed, minimum, and flex.

    Fixed tracks keep their size and flex tracks share whatever is left. When
    the fixed sizes alone overflow the space, every track is scaled down
    proportionally so a box never paints outside its own rectangle.

    Args:
        available: Cells the box has on the main axis.
        tracks: Per-slot sizing requests, in layout order.
        cross: Cells the box has on the other axis, handed to a callable
            ``size``. A caller that only uses fixed numbers can leave it out, in
            which case a callable would receive ``available`` instead.
    """
    available = max(0, available)
    if not tracks:
        return []
    extent = available if cross is None else cross
    fixed = [track.fixed(available, extent) for track in tracks]
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
