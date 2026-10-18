"""The companion that sits on the conversation: a small sprite with a few moods.

A :class:`Pet` is only data: a palette and, for each mood, the pixel maps it is drawn from, in the encoding
:mod:`zettcode.app.brand` already uses (``.`` is transparent, any other character names its colour). It
knows nothing of the terminal's size, of where it stands, or of the mouse; ``app/ui/widgets/pet.py`` places
it, moves it, and picks the mood. The default pet is the project's own mark, drawn again by hand at a
smaller size, because a half-size copy of the full mark would blur its eyes to nothing.

Every frame of a pet is the same size, and its height is an even number of pixel rows: two pixels fit in
one terminal cell.
"""

from __future__ import annotations

from collections.abc import Mapping

from ..tui.render.style import TextLine
from .brand import LOGO_PALETTE, pixel_lines

#: The moods a pet may have. ``idle`` is the only one it must have; a pet without the others stays as it is.
IDLE = "idle"
WORKING = "working"
GLAD = "glad"


class Pet:
    """A sprite and the frames of each of its moods.

    Args:
        name: What the pet is called.
        palette: The colour of each pixel character the frames use.
        poses: For each mood, the frames it cycles through, each frame a tuple of equal-length pixel rows.

    Raises:
        ValueError: There is no ``idle`` pose, a frame differs in size from the first, or its height is odd.
    """

    def __init__(self, name: str, palette: Mapping[str, str], poses: Mapping[str, tuple[tuple[str, ...], ...]]) -> None:
        """Check the frames agree, and draw each into cells once."""
        if IDLE not in poses:
            raise ValueError(f"pet {name!r} has no {IDLE!r} pose")
        first = poses[IDLE][0]
        size = (len(first[0]), len(first))
        for pose, frames in poses.items():
            if not frames:
                raise ValueError(f"pet {name!r}: pose {pose!r} has no frames")
            for frame in frames:
                if (len(frame[0]), len(frame)) != size or any(len(row) != size[0] for row in frame):
                    raise ValueError(f"pet {name!r}: a frame of {pose!r} is not {size[0]}x{size[1]}")
        if size[1] % 2:
            raise ValueError(f"pet {name!r}: {size[1]} pixel rows do not fill whole cells")
        self.name = name
        #: Columns and rows of cells the pet takes.
        self.width = size[0]
        self.height = size[1] // 2
        self._cells: dict[str, tuple[tuple[TextLine, ...], ...]] = {
            pose: tuple(pixel_lines(frame, dict(palette)) for frame in frames) for pose, frames in poses.items()
        }

    def frames(self, pose: str) -> int:
        """Return how many frames the mood has; a mood the pet lacks has its idle frames."""
        return len(self._cells.get(pose, self._cells[IDLE]))

    def lines(self, pose: str, step: int = 0) -> tuple[TextLine, ...]:
        """Return the cells of one frame of a mood, counting steps round the frames it has."""
        frames = self._cells.get(pose, self._cells[IDLE])
        return frames[step % len(frames)]


_RESTING = (
    ".FFFFFFF.",
    "EFDIDIDFE",
    "EFDIDIDFE",
    "EFDHDHDFE",
    ".FDDHDDF.",
    "..FFFFF..",
)
_BEATING = (
    ".FFFFFFF.",
    "EFDIDIDFE",
    "EFDIDIDFE",
    "EFDHHHDFE",
    ".FDDHDDF.",
    "..FFFFF..",
)
_PLEASED = (
    ".FFFFFFF.",
    "EFDIDIDFE",
    "EFDDDDDFE",
    "EFDHHHDFE",
    ".FDDHDDF.",
    "..FFFFF..",
)

#: The default pet: the mark, nine pixels by six, with the same face, ears and warm heart. Its heart beats
#: while a request runs, and it narrows its eyes when it is clicked.
ZETT = Pet(
    "zett",
    LOGO_PALETTE,
    {
        IDLE: (_RESTING,),
        WORKING: (_RESTING, _BEATING),
        GLAD: (_PLEASED, _BEATING),
    },
)

DEFAULT_PET = ZETT
