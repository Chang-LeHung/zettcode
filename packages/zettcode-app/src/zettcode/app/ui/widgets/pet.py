"""The pet that stands on the conversation and can be dragged anywhere on it."""

from __future__ import annotations

from collections.abc import Callable
from time import monotonic

from zettcode.app.pets import GLAD, IDLE, WORKING, Pet
from zettcode.tui import Canvas, Host, MouseAction, MouseEvent, Rect, TextLine, Widget

#: Columns left between the pet and the right edge of its ground at its resting place, the margin the
#: header, the status line and the composer keep.
MARGIN = 2

#: The least room the conversation must have for the pet to be drawn: columns, so that it does not take a
#: noticeable part of every line, and rows above and below it.
MIN_WIDTH = 80
ROOM_HIGH = 3

#: How long a click leaves the pet pleased, and how long each frame of a mood is held.
GLAD_SECONDS = 0.9
FRAME_SECONDS = 0.5


def paint_sprite(canvas: Canvas, lines: tuple[TextLine, ...], x: int, y: int) -> None:
    """Paint a pet's cells with their top left corner at a cell, leaving the cells it does not cover as they were.

    A cell the sprite leaves empty is skipped rather than written as a space, so whatever is under it shows
    through; a cell with a colour for only one half takes the background that was already there.
    """
    for row, line in enumerate(lines):
        column = x
        for span in line.spans:
            for character in span.text:
                if character != " " or span.style.background is not None:
                    canvas.set_cell(column, y + row, character, span.style)
                column += 1


class PetView(Widget):
    """Draw a pet over the right-hand middle of its ground, and move it with the mouse.

    Shape::

        ┌ conversation ────────────────────────────────┐
        │  ...                                         │
        │  ...                                  ▄█▀▀▀█▄ │
        │  ...                                  ██▀█▀██ │   <- press on it and drag it anywhere
        │  ...                                   ▀▀▀▀▀  │      on its ground
        │  ...                                         │
        ├ composer ────────────────────────────────────┤   <- which is part of the ground
        └──────────────────────────────────────────────┘

    The pet's place is kept as the fraction of the free room it stands at, left to right and top to bottom,
    so it keeps its place when the terminal is resized or a panel opens over it. It
    starts at the right edge, halfway down, or where it was last left: a drag that moved it reports the place
    through ``on_moved``, and the next start passes it back as ``position``. The ground is what ``area`` says:
    the shell gives it the conversation and the composer, so the pet can stand on the box the reader types in; a drag
    cannot take it onto the bars. A panel is a screen above this one and covers it. A press that does not move is a
    pat, and the pet is pleased for a moment.
    It sleeps while nothing runs, wakes and goes about its business while a request does, and its cells that are
    empty let the conversation show through. The wheel over it scrolls the conversation as it would anywhere else.

    The pet is drawn only when the reader has not hidden it (``pet`` in ``/statusline``) and the
    conversation is wide and tall enough to leave it room; otherwise it takes none and catches no clicks.

    Args:
        pet: The sprite and its moods.
        area: The rectangle the pet may stand in, asked for on every layout.
        shown: Whether the reader wants a pet at all.
        busy: Whether a request is running.
        forward: The widget a wheel turn over the pet is handed to.
        position: Where the pet stood when it was last left, as the two shares described above; ``None`` starts
            it at the right edge, halfway down.
        on_moved: Called with the two shares when a drag that moved the pet ends, so the place can be remembered.
    """

    def __init__(
        self,
        pet: Pet,
        *,
        area: Callable[[], Rect],
        shown: Callable[[], bool] = lambda: True,
        busy: Callable[[], bool] = lambda: False,
        forward: Widget | None = None,
        position: tuple[float, float] | None = None,
        on_moved: Callable[[float, float], None] | None = None,
    ) -> None:
        """Start where it was left, or at the right edge halfway down, resting."""
        super().__init__()
        self.pet = pet
        self._area = area
        self._shown = shown
        self._busy = busy
        self._forward = forward
        self._on_moved = on_moved
        #: Where the pet stands in the free room, from 0 (left, top) to 1 (right, bottom).
        self.fx, self.fy = position if position is not None else (1.0, 0.5)
        #: Where inside the pet the pointer holds it, while a press is down. It follows the pet and not the press:
        #: when the area stops the pet, the pointer goes on and this grows by what the area took, so the way back
        #: starts at once instead of after the whole distance the pointer went past the edge.
        self._grab: tuple[int, int] | None = None
        #: The cell the press landed on, so "did the pointer move" is a question about the pointer and not about
        #: whether the area let the pet follow it.
        self._pressed_at: tuple[int, int] | None = None
        self._moved = False
        self._glad_since: float | None = None
        #: The mood and frame the last paint drew, so a tick can tell whether anything moved.
        self._drawn: tuple[str, int] | None = None
        self._token = f"pet:{id(self)}"

    @property
    def selects_text(self) -> bool:
        """Own the drag that starts on the pet, so moving it does not mark the cells it crosses for copying."""
        return True

    @property
    def visible(self) -> bool:
        """Return whether the pet is wanted and the conversation leaves it room."""
        if not self._shown():
            return False
        area = self._area()
        return area.width >= MIN_WIDTH and area.height >= self.pet.height + ROOM_HIGH

    def set_pet(self, pet: Pet) -> None:
        """Swap the sprite for another pet's, which stands where the last one did (as a share of the room)."""
        if pet is self.pet:
            return
        self.pet = pet
        self._drawn = None
        if self.app is not None:
            self.app.request_layout()

    @property
    def mood(self) -> str:
        """Return the mood the pet is in: pleased after a pat, awake while a request runs, else asleep."""
        if self._glad_since is not None:
            return GLAD
        return WORKING if self._busy() else IDLE

    def _now(self) -> float:
        return self.app.clock() if self.app is not None else monotonic()

    def layout(self, rect: Rect) -> None:
        """Stand where the fractions say inside the area; an empty rectangle when there is no room or no wish."""
        super().layout(self._stand() if self.visible else Rect(0, 0, 0, 0))

    def _stand(self) -> Rect:
        """Return the rectangle the pet occupies for its fractions, inside the area."""
        area = self._area()
        free_x = max(0, area.width - self.pet.width - MARGIN)
        free_y = max(0, area.height - self.pet.height)
        return Rect(area.x + round(self.fx * free_x), area.y + round(self.fy * free_y), self.pet.width, self.pet.height)

    def _picture(self) -> tuple[str, int]:
        """Return the mood and the frame of it that is showing: the frames take turns on the clock.

        A pat counts its frames from the pat, so the pet always begins pleased; any other mood counts from
        zero. With reduced motion the pet keeps the first frame of its mood: the beat is decoration.
        """
        mood = self.mood
        frames = self.pet.frames(mood)
        if frames == 1 or (self.app is not None and self.app.reduced_motion):
            return mood, 0
        origin = self._glad_since if self._glad_since is not None else 0.0
        return mood, int((self._now() - origin) / FRAME_SECONDS) % frames

    def on_tick(self) -> bool:
        """End a pat that has lasted long enough, and say whether the picture is not the one last drawn."""
        if self._glad_since is not None and self._now() - self._glad_since >= GLAD_SECONDS:
            self._glad_since = None
            self._release()
        if self.visible == self.rect.empty:
            # Wanted and not placed, or placed and no longer wanted: the layout has to hear of it.
            if self.app is not None:
                self.app.request_layout()
            return True
        return not self.rect.empty and self._picture() != self._drawn

    def render(self, canvas: Canvas) -> None:
        """Paint the frame for the mood, leaving the cells the sprite does not cover as they were."""
        if self.rect.empty or not self.visible:
            return
        self._drawn = self._picture()
        paint_sprite(canvas, self.pet.lines(*self._drawn), self.rect.x, self.rect.y)

    def handle(self, event, host: Host) -> bool:
        """Take hold on a press, follow the pointer while it is held, and pat the pet if it never moved."""
        if not isinstance(event, MouseEvent):
            return False
        if event.action in (MouseAction.SCROLL_UP, MouseAction.SCROLL_DOWN):
            return self._forward is not None and self._forward.handle(event, host)
        if event.action is MouseAction.DOWN and event.button == 0:
            self._grab = (event.x - self.rect.x, event.y - self.rect.y)
            self._pressed_at = (event.x, event.y)
            self._moved = False
            return True
        if self._grab is None:
            return False
        if event.action is MouseAction.MOVE:
            if (event.x, event.y) != self._pressed_at:
                self._moved = True
            self._drag_to(event.x, event.y)
            return True
        if event.action is MouseAction.UP:
            if not self._moved:
                self._pat()
            elif self._on_moved is not None:
                self._on_moved(self.fx, self.fy)
            self._grab = None
            self._pressed_at = None
            return True
        return False

    def _drag_to(self, pointer_x: int, pointer_y: int) -> None:
        """Put the pet under the pointer, as far as the area lets it, and remember where it stands as fractions.

        What the area takes off the move is added to the grab, so the pointer is again over the same place on the
        pet that it would be if the pet had reached it: coming back from past the edge moves the pet at the first
        cell, and not after the pointer has crossed everything it overshot.
        """
        area = self._area()
        grab_x, grab_y = self._grab or (0, 0)
        free_x = max(0, area.width - self.pet.width - MARGIN)
        free_y = max(0, area.height - self.pet.height)
        if free_x:
            self.fx = min(1.0, max(0.0, (pointer_x - grab_x - area.x) / free_x))
        if free_y:
            self.fy = min(1.0, max(0.0, (pointer_y - grab_y - area.y) / free_y))
        self.rect = self._stand()
        self._grab = (pointer_x - self.rect.x, pointer_y - self.rect.y)

    def _pat(self) -> None:
        """Please the pet for a moment; the clock ends it, so it passes without any further input."""
        self._glad_since = self._now()
        if self.app is not None:
            self.app.scheduler.animate(self._token)
            self.app.invalidate()

    def _release(self) -> None:
        """Give the frame loop back."""
        if self.app is not None:
            self.app.scheduler.animate(self._token, active=False)

    def on_unmount(self) -> None:
        """Release the frame loop, so a pet put away mid-pat stops costing frames."""
        self._release()
