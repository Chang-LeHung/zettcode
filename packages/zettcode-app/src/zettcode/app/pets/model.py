"""What a pet is, and the catalog that finds one by name.

A :class:`Pet` is only data: a palette and, for each mood, the pixel maps it is drawn from, in the encoding
:mod:`zettcode.app.brand` already uses (``.`` is transparent, any other character names its colour). It
knows nothing of the terminal's size, of where it stands, or of the mouse; ``app/ui/widgets/pet.py`` places
it, moves it, and picks the mood.

Pets are offered the way palettes are: a :class:`PetSource` names one and builds it only when it is asked for,
the built-in plugin offers the ones that ship, and any other plugin offers its own through
``ctx.tui.register_pet``. :class:`PetCatalog` is what ``/pet`` and the start-up read.

Every frame of a pet is the same size, and its height is an even number of pixel rows: two pixels fit in
one terminal cell.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from typing import NamedTuple

from zettcode.app.brand import pixel_lines
from zettcode.tui.render.style import TextLine

#: The moods a pet may have. ``idle`` is the only one it must have; a pet without the others stays as it is.
#: A pet is asleep when it is idle, awake and busy while a request runs, and pleased when it is patted.
IDLE = "idle"
WORKING = "working"
GLAD = "glad"

#: What a pet may be called: one word, the way a palette's name is, because it is typed after ``/pet``.
PET_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def _brightness(colour: str) -> int:
    """Return the mean of a ``#rrggbb`` colour's channels, 0 to 255."""
    return sum(int(colour[index : index + 2], 16) for index in (1, 3, 5)) // 3


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
        self.palette = dict(palette)
        self.poses = dict(poses)
        #: Columns and rows of cells the pet takes.
        self.width = size[0]
        self.height = size[1] // 2
        self._cells: dict[str, tuple[tuple[TextLine, ...], ...]] = {
            pose: tuple(pixel_lines(frame, self.palette) for frame in frames) for pose, frames in poses.items()
        }

    def swatch(self, count: int = 3) -> tuple[str, ...]:
        """Return the colours this pet is mostly made of, most used first, for a chip that stands for it.

        Read from its resting frame. The near-black of eyes and outlines is left out: it says nothing about the
        pet and would disappear on a dark page.
        """
        used = Counter(char for row in self.poses[IDLE][0] for char in row if char != ".")
        colours: list[str] = []
        for char, _ in used.most_common():
            colour = self.palette.get(char)
            if colour and colour not in colours and _brightness(colour) >= 70:
                colours.append(colour)
        return tuple(colours[:count])

    def frames(self, pose: str) -> int:
        """Return how many frames the mood has; a mood the pet lacks has its idle frames."""
        return len(self._cells.get(pose, self._cells[IDLE]))

    def lines(self, pose: str, step: int = 0) -> tuple[TextLine, ...]:
        """Return the cells of one frame of a mood, counting steps round the frames it has."""
        frames = self._cells.get(pose, self._cells[IDLE])
        return frames[step % len(frames)]


def mirrored(halves: tuple[str, ...]) -> tuple[str, ...]:
    """Return a frame drawn as its left half only, completed by its own reflection.

    Most creatures are symmetric, and drawing one side keeps the two from drifting apart as the art is edited. A
    mood that is not symmetric (an eye that looks aside, a tail) replaces whole rows with :func:`edited`.
    """
    return tuple(row + row[::-1] for row in halves)


def edited(frame: tuple[str, ...], rows: Mapping[int, str]) -> tuple[str, ...]:
    """Return a frame with some of its pixel rows replaced, which is how one mood is made from another.

    Raises:
        ValueError: A row index is outside the frame, or a new row is not as wide as the frame.
    """
    changed = list(frame)
    for index, row in rows.items():
        if not 0 <= index < len(frame) or len(row) != len(frame[0]):
            raise ValueError(f"row {index} cannot be replaced by {row!r}")
        changed[index] = row
    return tuple(changed)


class PetSource(NamedTuple):
    """A pet that something offers by name: the program's own, or a plugin.

    Attributes:
        name: What ``/pet`` is typed with; one word.
        load: Builds the pet. Called when it is asked for, never before, so a source costs nothing until picked.
        description: The one-line note the menu shows beside the name, or a function that returns it (called only
            when the menu is opened).
    """

    name: str
    load: Callable[[], Pet]
    description: str | Callable[[], str] = ""


class PetCatalog:
    """Every pet that can be asked for by name, in the order a menu lists them.

    A source whose name is taken, or is not one word, is ignored: the first one wins, so the pets that ship are
    never displaced by a plugin's and the menu never lists a name twice. Only names are listed up front; a pet is
    built when it is asked for.

    Args:
        sources: What the program and the plugins offer, in load order.
    """

    def __init__(self, sources: Sequence[PetSource] = ()) -> None:
        chosen: dict[str, PetSource] = {}
        for source in sources:
            if source.name not in chosen and PET_NAME.fullmatch(source.name):
                chosen[source.name] = source
        self._sources = chosen

    def names(self) -> tuple[str, ...]:
        """Return the names in the order a menu lists them. Nothing is built."""
        return tuple(self._sources)

    def load(self, name: str) -> Pet:
        """Return the pet called ``name``.

        Raises:
            ValueError: There is no such pet, or it could not be built. The message names what is available, so
                a typo is answered by the list.
        """
        source = self._sources.get(name)
        if source is None:
            available = ", ".join(self.names()) or "none"
            raise ValueError(f"Unknown pet: {name!r}. Available: {available}")
        try:
            return source.load()
        except Exception as error:  # noqa: BLE001 - a plugin's pet is its author's code
            raise ValueError(f"Pet {name!r} could not be built: {error}") from error

    def notes(self) -> dict[str, str]:
        """Return the one-line note each pet carries, by name; a pet with none is left out.

        Whatever cannot be read has no note, and is not an error here: it is the error of the person who picks it.
        """
        notes: dict[str, str] = {}
        for name, source in self._sources.items():
            try:
                described = source.description
                text = described() if callable(described) else described
            except Exception:  # noqa: BLE001 - see above
                continue
            if isinstance(text, str) and text.strip():
                notes[name] = text.strip()
        return notes
