"""The bottom panel ``/pet`` opens: every pet by name, with the marked one on a stage at the right."""

from __future__ import annotations

from collections.abc import Callable
from time import monotonic

from zettcode.app.pets import GLAD, IDLE, WORKING, Pet, PetCatalog
from zettcode.tui import ARROW_DOWN, ARROW_UP, SEPARATOR, Canvas, Host, MouseAction, MouseEvent, Widget
from zettcode.tui.render import Style, blend, display_width, truncate

from .panel import pressed
from .pet import paint_sprite

#: Rows the panel needs besides the list: a blank, the title and a blank above it, and the keys below.
CHROME = 4

#: The first row of the list, counted from the top of the panel.
LIST_TOP = 3

#: The stage the marked pet stands on, at the right: columns, and rows. A pet is up to seven rows tall and stands
#: on the floor line whatever its height, so the name and the mood under it do not move as the mark does: a pad,
#: the sprite's seven, the floor, a blank, the name and the mood.
BOX_WIDTH = 24
SPRITE_ROWS = 7
BOX_HEIGHT = 12

#: The least columns the panel must have for the stage to be drawn beside the list rather than not at all.
MIN_WIDTH_FOR_BOX = 62

#: The rows of the screen the panel leaves to the conversation above it.
LEFT_FOR_CONVERSATION = 8

#: Columns a pet's name takes in the list, and the colour chip before it.
NAME_WIDTH = 9
CHIP = 3

#: How long the stage holds each step of the mood it shows the marked pet in.
STEP_SECONDS = 0.6

#: What the stage shows, step after step: the mood, the frame of it, and the word and colour role it is told by.
SEQUENCE: tuple[tuple[str, int, str], ...] = (
    (IDLE, 0, "asleep"),
    (IDLE, 0, "asleep"),
    (WORKING, 0, "at work"),
    (WORKING, 1, "at work"),
    (WORKING, 0, "at work"),
    (WORKING, 1, "at work"),
    (GLAD, 0, "pleased"),
    (GLAD, 1, "pleased"),
)

#: The three moods in the order the steps go through them, for the row of dots under the name.
MOODS: tuple[tuple[str, str], ...] = ((IDLE, "asleep"), (WORKING, "at work"), (GLAD, "pleased"))


def pet_rows(count: int, height: int) -> int:
    """Return the rows to ask for: the whole list when the screen has room for it, else what it can spare."""
    wanted = CHROME + max(count, BOX_HEIGHT)
    return max(CHROME + 3, min(wanted, height - LEFT_FOR_CONVERSATION))


class PetPage(Widget):
    """Choose a pet: the list at the left, the marked pet going through its moods on a stage at the right.

    Shape::

        Pet                                                                            7 pets

          ▸ ■■■ cat ●    a green cat in a bell collar; it watches the work     ┌──────────────────────┐
            ■■■ dog      a tan dog; it looks along the work and wags its ears   │      (sprite)        │
            ■■■ tiger    a tiger cub; it keeps watch while a request runs       │ ▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁ │
            ...                                                                 │         cat          │
          ↑ ↓ pet · enter choose · esc cancel                                   │ ● at work ○ ○        │
                                                                                └──────────────────────┘

    The chip before each name is the three colours the pet is mostly made of, read from its own sprite, and the
    stage is tinted with the first. Up and Down move the mark, and every move puts the marked pet over the
    conversation too, where it will stand, so it can be judged there as well as on the stage; Escape puts the one
    that was there back. Enter chooses. The stage shows the marked pet asleep, at work and pleased in turn, from
    the clock, so it passes by itself and costs nothing once the panel is put away.

    Args:
        catalog: Every pet that can be asked for.
        current: The name of the pet that is out now; the mark starts on it and the list marks it.
        on_move: Called with the name of a pet when the mark comes to rest on it.
        on_select: Called with the name of the pet Enter chose.
        on_cancel: Called when the reader backs out.
    """

    HINT = f"{ARROW_UP} {ARROW_DOWN} pet {SEPARATOR} enter choose {SEPARATOR} esc cancel"

    def __init__(
        self,
        catalog: PetCatalog,
        current: str,
        *,
        on_move: Callable[[str], None],
        on_select: Callable[[str], None],
        on_cancel: Callable[[], None],
    ) -> None:
        """Start with the mark on the pet that is out now, or on the first when it is not one of these."""
        super().__init__()
        self.catalog = catalog
        self.names = catalog.names()
        self.notes = catalog.notes()
        self.current = current
        self.on_move = on_move
        self.on_select = on_select
        self.on_cancel = on_cancel
        self.mark = self.names.index(current) if current in self.names else 0
        #: The first visible row of the list.
        self.top = 0
        self._loaded: dict[str, Pet | None] = {}
        self._token = f"pet-panel:{id(self)}"
        self._began = monotonic()
        self._drawn: int | None = None

    @property
    def focusable(self) -> bool:
        """Take focus when the shell pushes the page, so the keys reach it."""
        return True

    @property
    def marked(self) -> str:
        """Return the name of the pet the mark is on."""
        return self.names[self.mark]

    def _now(self) -> float:
        return self.app.clock() if self.app is not None else monotonic()

    def on_mount(self) -> None:
        """Start the clock the stage moves by, and count the steps from now."""
        self._began = self._now()
        if self.app is not None and not self.app.reduced_motion:
            self.app.scheduler.animate(self._token)

    def on_unmount(self) -> None:
        """Release the frame loop, so a panel put away stops costing frames."""
        if self.app is not None:
            self.app.scheduler.animate(self._token, active=False)

    def _step(self) -> int:
        """Return which step of the sequence the stage is on; a still stage shows the pet at work."""
        if self.app is not None and self.app.reduced_motion:
            return 2
        return int((self._now() - self._began) / STEP_SECONDS) % len(SEQUENCE)

    def on_tick(self) -> bool:
        """Say whether the stage shows a different step from the one last drawn."""
        return self._step() != self._drawn

    def _pet(self, name: str) -> Pet | None:
        """Return the pet called ``name``, built once; ``None`` when it could not be built."""
        if name not in self._loaded:
            try:
                self._loaded[name] = self.catalog.load(name)
            except ValueError:
                self._loaded[name] = None
        return self._loaded[name]

    def capture_event(self, event, host: Host) -> bool:
        """Take Escape before the focused widget can."""
        if pressed(event) == "escape":
            self.on_cancel()
            return True
        return False

    def handle(self, event, host: Host) -> bool:
        """Move the mark with the arrows, and choose with Enter."""
        if isinstance(event, MouseEvent):
            return self._handle_mouse(event)
        match pressed(event):
            case "up" | "backtab":
                self._wrap(-1)
            case "down" | "tab":
                self._wrap(1)
            case "pageup":
                self._move(self.mark - max(1, self._view() - 1))
            case "pagedown":
                self._move(self.mark + max(1, self._view() - 1))
            case "home":
                self._move(0)
            case "end":
                self._move(len(self.names) - 1)
            case "enter":
                self.on_select(self.marked)
            case _:
                return False
        return True

    def _handle_mouse(self, event: MouseEvent) -> bool:
        """Mark the pet under a click, and choose it when it was already marked; the wheel moves the mark."""
        if event.action is MouseAction.SCROLL_UP:
            self._move(self.mark - 1)
            return True
        if event.action is MouseAction.SCROLL_DOWN:
            self._move(self.mark + 1)
            return True
        if event.action is not MouseAction.DOWN:
            return False
        offset = event.y - (self.rect.y + LIST_TOP)
        index = self.top + offset
        if not 0 <= offset < self._view() or index >= len(self.names):
            return False
        if index == self.mark:
            self.on_select(self.marked)
        else:
            self._move(index)
        return True

    def _wrap(self, step: int) -> None:
        """Move the mark one pet, going round: up from the first lands on the last, down from the last on the first."""
        self._move((self.mark + step) % len(self.names))

    def _move(self, index: int) -> None:
        """Put the mark on a pet, within the list, and tell whoever shows the pet over the conversation."""
        index = max(0, min(len(self.names) - 1, index))
        if index != self.mark:
            self.mark = index
            self.on_move(self.marked)

    def _view(self) -> int:
        """Return how many rows of the list the panel has room for."""
        return max(1, self.rect.height - CHROME)

    def _reveal(self) -> None:
        """Scroll the list the least that shows the marked pet."""
        view = self._view()
        if self.mark < self.top:
            self.top = self.mark
        if self.mark >= self.top + view:
            self.top = self.mark - view + 1
        self.top = max(0, min(self.top, len(self.names) - view))

    def render(self, canvas: Canvas) -> None:
        """Fill the panel, then draw the title, the list, the stage and the keys."""
        if self.rect.empty:
            return
        theme = self.theme
        surface = theme.surface_alt
        canvas.fill(self.rect.x, self.rect.y, self.rect.width, self.rect.height, Style(background=surface))
        x = self.rect.x + 2
        room = max(0, self.rect.width - 4)
        muted = Style(foreground=theme.muted, background=surface)
        canvas.draw_text(x, self.rect.y + 1, "Pet", Style(foreground=theme.text, background=surface, bold=True))
        count = f"{len(self.names)} pets"
        canvas.draw_text(self.rect.right - 2 - display_width(count), self.rect.y + 1, count, muted)
        boxed = self.rect.width >= MIN_WIDTH_FOR_BOX and self._view() >= BOX_HEIGHT
        list_right = self.rect.right - 2 - (BOX_WIDTH + 2 if boxed else 0)
        self._reveal()
        self._draw_list(canvas, x, list_right)
        if boxed:
            self._draw_stage(canvas, self.rect.right - 2 - BOX_WIDTH, self.rect.y + LIST_TOP)
        canvas.draw_text(x, self.rect.bottom - 1, truncate(self.HINT, room), muted, max_width=room)

    def _draw_list(self, canvas: Canvas, x: int, right: int) -> None:
        """Draw the visible rows: a marker, the colour chip, the name, a dot for the one out now, and its note."""
        theme = self.theme
        surface = theme.surface_alt
        for offset in range(self._view()):
            index = self.top + offset
            if index >= len(self.names):
                break
            y = self.rect.y + LIST_TOP + offset
            name = self.names[index]
            marked = index == self.mark
            style = Style(foreground=theme.text if marked else theme.muted, background=surface, bold=marked)
            if marked:
                canvas.draw_text(x, y, "\u25b8", Style(foreground=theme.accent, background=surface, bold=True))
            pet = self._pet(name)
            colours = pet.swatch(CHIP) if pet is not None else ()
            for slot in range(CHIP):
                # An unmarked row's chip is toned down towards the panel, so the marked one is the one in colour.
                colour = colours[slot] if slot < len(colours) else theme.muted
                shown = colour if marked else blend(colour, surface, 0.45)
                canvas.draw_text(x + 2 + slot, y, "\u25a0", Style(foreground=shown, background=surface))
            label = x + 2 + CHIP + 1
            canvas.draw_text(label, y, truncate(name, NAME_WIDTH - 2), style, max_width=NAME_WIDTH - 2)
            if name == self.current:
                canvas.draw_text(
                    label + min(display_width(name), NAME_WIDTH - 2) + 1,
                    y,
                    "\u25cf",
                    Style(foreground=theme.accent, background=surface),
                )
            start = label + NAME_WIDTH
            room = right - start
            if room >= 12:
                canvas.draw_text(
                    start,
                    y,
                    truncate(self.notes.get(name, ""), room),
                    Style(foreground=blend(theme.muted, surface, 0.15), background=surface),
                    max_width=room,
                )
        edge = Style(foreground=theme.muted, background=surface)
        if self.top > 0:
            canvas.draw_text(right - 1, self.rect.y + LIST_TOP, "\u25b2", edge)
        if self.top + self._view() < len(self.names):
            canvas.draw_text(right - 1, self.rect.y + LIST_TOP + self._view() - 1, "\u25bc", edge)

    def _mood_colour(self, pose: str) -> str:
        """Return the colour a mood is told in: quiet when asleep, the accent at work, the warm one when pleased."""
        theme = self.theme
        return {IDLE: theme.muted, WORKING: theme.accent, GLAD: theme.warning}[pose]

    def _draw_stage(self, canvas: Canvas, x: int, y: int) -> None:
        """Draw the marked pet on a stage tinted with its own colour, its name, and the mood it is in."""
        theme = self.theme
        pet = self._pet(self.marked)
        tint = pet.swatch(1)[0] if pet is not None and pet.swatch(1) else theme.accent
        stage = blend(theme.surface_alt, tint, 0.16)
        floor = blend(theme.surface_alt, tint, 0.38)
        canvas.fill(x, y, BOX_WIDTH, BOX_HEIGHT, Style(background=stage))
        step = self._step()
        self._drawn = step
        if pet is None:
            message = "could not be built"
            canvas.draw_text(
                x + (BOX_WIDTH - len(message)) // 2,
                y + BOX_HEIGHT // 2,
                message,
                Style(foreground=theme.muted, background=stage, italic=True),
            )
            return
        pose, frame, word = SEQUENCE[step]
        floor_y = y + 1 + SPRITE_ROWS
        paint_sprite(canvas, pet.lines(pose, frame), x + (BOX_WIDTH - pet.width) // 2, floor_y - pet.height)
        # The floor the pet stands on: one row of a deeper tint, as wide as the stage.
        canvas.fill(x, floor_y, BOX_WIDTH, 1, Style(background=floor))
        name_y = floor_y + 2
        canvas.draw_text(
            x + (BOX_WIDTH - display_width(pet.name)) // 2,
            name_y,
            pet.name,
            Style(foreground=theme.text, background=stage, bold=True),
        )
        # The three moods as a row of lit and unlit dots; the one the pet is in carries its colour and its word.
        parts = [(f"\u25cf {word}" if mood == pose else "\u25cb", mood) for mood, _ in MOODS]
        widths = [display_width(text) for text, _ in parts]
        column = x + (BOX_WIDTH - sum(widths) - 2 * (len(parts) - 1)) // 2
        for (text, mood), width in zip(parts, widths, strict=True):
            lit = mood == pose
            colour = self._mood_colour(mood) if lit else blend(theme.muted, stage, 0.5)
            canvas.draw_text(column, name_y + 1, text, Style(foreground=colour, background=stage, bold=lit))
            column += width + 2
