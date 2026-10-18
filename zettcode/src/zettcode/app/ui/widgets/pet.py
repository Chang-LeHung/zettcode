"""The pet that stands on the conversation and can be dragged anywhere on it."""

from __future__ import annotations

from collections.abc import Callable
from time import monotonic

from zettcode.app.pets import GLAD, IDLE, WORKING, Pet
from zettcode.tui import Canvas, Host, MouseAction, MouseEvent, Rect, TextLine, Widget

#: Columns left between the pet and the right edge of the conversation at its resting place, the margin the
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
    """Draw a pet over the right-hand middle of the conversation, and move it with the mouse.

    Shape::

        ┌ conversation ────────────────────────────────┐
        │  ...                                         │
        │  ...                                  ▄█▀▀▀█▄ │
        │  ...                                  ██▀█▀██ │   <- press on it and drag it anywhere
        │  ...                                   ▀▀▀▀▀  │      within the conversation
        │  ...                                         │
        └──────────────────────────────────────────────┘

    The pet's place is kept as the fraction of the free room it stands at, left to right and top to bottom,
    so it keeps its place in the conversation when the terminal is resized or a panel opens under it. It
    starts at the right edge, halfway down. A drag cannot take it out of the conversation, where it would
    cover the composer or a panel; a press that does not move is a pat, and the pet is pleased for a moment.
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
    """

    def __init__(
        self,
        pet: Pet,
        *,
        area: Callable[[], Rect],
        shown: Callable[[], bool] = lambda: True,
        busy: Callable[[], bool] = lambda: False,
        forward: Widget | None = None,
    ) -> None:
        """Start at the right edge, halfway down, resting."""
        super().__init__()
        self.pet = pet
        self._area = area
        self._shown = shown
        self._busy = busy
        self._forward = forward
        #: Where the pet stands in the free room, from 0 (left, top) to 1 (right, bottom).
        self.fx = 1.0
        self.fy = 0.5
        #: Where inside the pet the pointer took hold of it, while a press is down.
        self._grab: tuple[int, int] | None = None
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
            self._moved = False
            return True
        if self._grab is None:
            return False
        if event.action is MouseAction.MOVE:
            self._drag_to(event.x - self._grab[0], event.y - self._grab[1])
            return True
        if event.action is MouseAction.UP:
            if not self._moved:
                self._pat()
            self._grab = None
            return True
        return False

    def _drag_to(self, x: int, y: int) -> None:
        """Move the pet's corner towards a cell, as far as the area lets it, and remember it as fractions."""
        area = self._area()
        free_x = max(0, area.width - self.pet.width - MARGIN)
        free_y = max(0, area.height - self.pet.height)
        fx = min(1.0, max(0.0, (x - area.x) / free_x)) if free_x else self.fx
        fy = min(1.0, max(0.0, (y - area.y) / free_y)) if free_y else self.fy
        if (fx, fy) == (self.fx, self.fy):
            return
        self.fx, self.fy = fx, fy
        self._moved = True
        self.rect = self._stand()

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
