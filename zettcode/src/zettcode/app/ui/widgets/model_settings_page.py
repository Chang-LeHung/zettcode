"""The bottom panel ``/config`` opens for one model: every setting on a row, the name on the left and its value on the right."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from time import monotonic
from typing import Literal

from zettcode.tui import (
    ARROW_DOWN,
    ARROW_UP,
    PROMPT,
    SEPARATOR,
    AnyEvent,
    Canvas,
    Host,
    MouseAction,
    MouseEvent,
    Rect,
    Style,
    Widget,
    event_key,
)
from zettcode.tui.core.geometry import Point
from zettcode.tui.render import blend, display_width, truncate

from .form_page import LineArea, SecretLine
from .panel import pressed
from .self_compact_page import _Rail
from .statusline_page import SWITCH_WIDTH, draw_switch

#: What an answer is: the trimmed text of a typed row, whether a switch is on, the word a choice is on.
Answer = str | bool

#: The columns kept free at each side, the width of the marker before a row's label, and of the label itself.
MARGIN = 2
MARKER_WIDTH = 2
LABEL_WIDTH = 16

#: Rows besides the settings: the title, the reason a save was refused, a blank above the line that explains the row
#: the cursor is in, that line, and the keys.
CHROME_ROWS = 5

#: The gap between a switch's rail and its word, and between the words of a choice.
WORD_GAP = 1
CHOICE_GAP = 3

#: The marks of a choice: the word it is on, and the others.
ON, OFF = "\u25c9", "\u25cb"

Kind = Literal["text", "secret", "switch", "choice"]


@dataclass(frozen=True, slots=True)
class Setting:
    """One row of the panel: a value of the model that can be changed.

    Attributes:
        key: What the row is called in the answers handed to the page's owner.
        label: What the reader sees on the left.
        kind: ``text`` and ``secret`` are typed; ``switch`` is a rail with a knob between two words; ``choice`` is
            one word out of several.
        initial: The text a typed row starts with.
        placeholder: Shown, muted, while a typed row is empty.
        hint: One sentence shown under the rows while the cursor is in this one.
        required: Refuse a save while a typed row is empty; the label then carries a star.
        words: For a switch, the word of off and then of on; for a choice, its words.
        value: For a switch or a choice, the index of the word it starts on.
    """

    key: str
    label: str
    kind: Kind = "text"
    initial: str = ""
    placeholder: str = ""
    hint: str = ""
    required: bool = False
    words: tuple[str, ...] = ()
    value: int = 0


@dataclass(frozen=True, slots=True)
class Action:
    """One thing to do with the model, drawn as a row of its own under the settings.

    Attributes:
        key: What the page's owner is told was chosen.
        label: The row's name.
        note: What it does, in a few words; also the line under the rows while the cursor is on it.
        saves: Whether the settings are taken with it, and so refused when a required one is empty.
    """

    key: str
    label: str
    note: str
    saves: bool = False


class _Row(Widget):
    """What every row of the panel shares: the marker and the label on the left."""

    def __init__(self, page: ModelSettingsPage, label: str, *, hint: str = "", required: bool = False) -> None:
        """Hold the page the row is on, the words it is called, and the sentence that explains it."""
        super().__init__()
        self.page = page
        self.label = f"{label} *" if required else label
        self.hint = hint

    @property
    def here(self) -> bool:
        """Return whether the cursor is in this row."""
        return self.target.focused

    @property
    def target(self) -> Widget:
        """Return the widget that takes focus when the cursor moves to this row."""
        return self

    @property
    def column(self) -> int:
        """Return the column the row's value starts at."""
        return self.rect.x + MARGIN + MARKER_WIDTH + LABEL_WIDTH

    def draw_label(self, canvas: Canvas) -> None:
        """Draw the marker when the cursor is here, then the label."""
        theme = self.theme
        surface = theme.surface_alt
        x, y = self.rect.x + MARGIN, self.rect.y
        if self.here:
            canvas.draw_text(x, y, PROMPT, Style(foreground=theme.accent, background=surface, bold=True))
        canvas.draw_text(
            x + MARKER_WIDTH,
            y,
            truncate(self.label, LABEL_WIDTH - 1),
            Style(foreground=theme.text, background=surface, bold=self.here),
            max_width=LABEL_WIDTH - 1,
        )


class _TextRow(_Row):
    """A typed row: the editor sits on a band to the right of the label, so it reads as somewhere to type."""

    def __init__(self, page: ModelSettingsPage, setting: Setting) -> None:
        """Hold one editor, a bullet-painting one for a secret."""
        super().__init__(page, setting.label, hint=setting.hint, required=setting.required)
        self.setting = setting
        self.area: LineArea = (SecretLine if setting.kind == "secret" else LineArea)(
            prompt="", placeholder=setting.placeholder, max_height=1, on_change=page.edited
        )
        if setting.initial:
            self.area.set_text(setting.initial)

    @property
    def children(self) -> tuple[Widget, ...]:
        """Expose the editor."""
        return (self.area,)

    @property
    def target(self) -> Widget:
        """Return the editor: the cursor lives in it."""
        return self.area

    @property
    def answer(self) -> Answer:
        """Return what is typed, trimmed."""
        return self.area.text.strip()

    def layout(self, rect: Rect) -> None:
        """Put the editor after the label, as wide as the row has left."""
        super().layout(rect)
        if rect.empty:
            self.area.layout(Rect(rect.x, rect.y, 0, 0))
            return
        start = self.column
        self.area.layout(Rect(start, rect.y, max(0, rect.right - MARGIN - start), 1))

    def render(self, canvas: Canvas) -> None:
        """Draw the label, the band, and the editor."""
        if self.rect.empty:
            return
        self.draw_label(canvas)
        theme = self.theme
        band = Style(background=theme.surface)
        canvas.fill(self.area.rect.x - 1, self.area.rect.y, self.area.rect.width + 2, 1, band)
        self.area.render(canvas)

    def handle(self, event: AnyEvent, host: Host) -> bool:
        """Take a press on the label or the band's edge: the editor takes one inside it for itself."""
        if isinstance(event, MouseEvent) and event.action is MouseAction.DOWN and self.rect.contains(event.x, event.y):
            host.focus(self.area)
            return True
        return False

    def cursor(self) -> Point | None:
        """Forward the editor's cursor."""
        return self.area.cursor()


class _RailRow(_Row):
    """A switch or a choice: Left and Right move it, Space turns a switch over."""

    def __init__(self, page: ModelSettingsPage, setting: Setting) -> None:
        """Start the knob on the setting's word."""
        super().__init__(page, setting.label, hint=setting.hint)
        self.setting = setting
        self.rail = _Rail(setting.words, setting.value)
        self.switch = setting.kind == "switch"
        self._token = f"model-settings:{setting.key}:{id(self)}"
        #: Where each word of a choice was drawn at the last paint, for a click.
        self._spans: list[tuple[int, int]] = []

    @property
    def focusable(self) -> bool:
        """Take the cursor: there is no editor in the row to hold it."""
        return True

    @property
    def answer(self) -> Answer:
        """Return whether a switch is on, or the word a choice is on, once the knob arrives."""
        return bool(self.rail.selected) if self.switch else self.rail.words[self.rail.selected]

    def _now(self) -> float:
        return self.app.clock() if self.app is not None else monotonic()

    def choose(self, index: int) -> None:
        """Send the knob to a word; a switch slides there, a choice jumps."""
        instant = not self.switch or (self.app is not None and self.app.reduced_motion)
        if self.rail.choose(index, self._now(), instant=instant) and self.app is not None:
            self.app.scheduler.animate(self._token)
        self.page.edited()
        self.invalidate()

    def on_unmount(self) -> None:
        """Release the frame loop, so a panel put away mid-slide stops costing frames."""
        self.rail.moving = False
        if self.app is not None:
            self.app.scheduler.animate(self._token, active=False)

    def on_tick(self) -> bool:
        """Hand the frame loop back once the knob has arrived; say whether the picture is still changing."""
        landed = self.rail.arrive(self._now())
        if not self.rail.moving and self.app is not None:
            self.app.scheduler.animate(self._token, active=False)
        return self.rail.moving or landed

    def handle(self, event: AnyEvent, host: Host) -> bool:
        """Move with Left and Right (Home and End go to the ends), and turn over or step on with Space."""
        if isinstance(event, MouseEvent):
            return self._press(event, host)
        last = len(self.rail.words) - 1
        match pressed(event):
            case "left":
                self.choose(self.rail.selected - 1)
            case "right":
                self.choose(self.rail.selected + 1)
            case "home":
                self.choose(0)
            case "end":
                self.choose(last)
            case " ":
                self.choose((self.rail.selected + 1) % (last + 1))
            case _:
                return False
        return True

    def _press(self, event: MouseEvent, host: Host) -> bool:
        """Put the cursor here, and set the switch or the word under the click."""
        if event.action is not MouseAction.DOWN or not self.rect.contains(event.x, event.y):
            return False
        host.focus(self)
        if self.switch:
            if (
                self.column
                <= event.x
                < self.column + SWITCH_WIDTH + WORD_GAP + max(map(display_width, self.rail.words))
            ):
                self.choose(1 - self.rail.selected)
        else:
            for index, (start, stop) in enumerate(self._spans):
                if start <= event.x < stop:
                    self.choose(index)
        return True

    def render(self, canvas: Canvas) -> None:
        """Draw the label, then the rail and its word, or the words with the chosen one marked."""
        if self.rect.empty:
            return
        self.draw_label(canvas)
        theme = self.theme
        surface = theme.surface_alt
        y = self.rect.y
        if self.switch:
            position = self.rail.position(self._now())
            on = bool(self.rail.selected)
            draw_switch(canvas, theme, y, self.column, position, blend(theme.muted, surface, 0.55))
            canvas.draw_text(
                self.column + SWITCH_WIDTH + WORD_GAP,
                y,
                self.rail.words[self.rail.selected],
                Style(foreground=theme.accent if on else blend(theme.muted, surface, 0.25), background=surface),
                max_width=max(0, self.rect.right - MARGIN - self.column - SWITCH_WIDTH - WORD_GAP),
            )
            return
        x = self.column
        self._spans = []
        for index, word in enumerate(self.rail.words):
            chosen = index == self.rail.selected
            width = display_width(word) + 2
            self._spans.append((x, x + width))
            style = (
                Style(foreground=theme.accent, background=surface, bold=True)
                if chosen
                else Style(foreground=theme.muted, background=surface)
            )
            canvas.draw_text(x, y, f"{ON if chosen else OFF} {word}", style, max_width=max(0, self.rect.right - x))
            x += width + CHOICE_GAP


class _ActionRow(_Row):
    """A thing to do rather than a value: the label, and what it does beside it."""

    def __init__(self, page: ModelSettingsPage, action: Action) -> None:
        """Hold the action and the words it is drawn with."""
        super().__init__(page, action.label, hint=action.note)
        self.action = action

    @property
    def focusable(self) -> bool:
        """Take the cursor, so Enter does it."""
        return True

    def render(self, canvas: Canvas) -> None:
        """Draw the label and, muted after it, what it does."""
        if self.rect.empty:
            return
        self.draw_label(canvas)
        theme = self.theme
        room = max(0, self.rect.right - MARGIN - self.column)
        canvas.draw_text(
            self.column,
            self.rect.y,
            truncate(self.action.note, room),
            Style(foreground=blend(theme.muted, theme.surface_alt, 0.15), background=theme.surface_alt),
            max_width=room,
        )

    def handle(self, event: AnyEvent, host: Host) -> bool:
        """Put the cursor here on a press, and do it on a second one."""
        if isinstance(event, MouseEvent) and event.action is MouseAction.DOWN and self.rect.contains(event.x, event.y):
            if self.here:
                self.page.act(self.action, host)
            else:
                host.focus(self)
            return True
        return False


class ModelSettingsPage(Widget):
    """Change everything about one model on one page, and save it all at once.

    Shape::

        GPT-6.1-sol (current)                                        edited
        ● address: write it as https://host/v1             <- why the last save was refused
        ▸ Token           ••••••••••••
          API             ◉ chat   ○ responses   ○ anthropic
          Address         http://tds.com:8787
          Model id *      gpt-6.1-sol
          Shown name      GPT-6.1-sol
          Images          ━━━━━━━━━●  accepted
          Web search      ●─────────  off
          Search tool     web_search_20260318
          Temperature     the provider's default
          Context window  1m
          Compress at     80

          Use this model  save, then switch to it now
          Remove          delete it from the file

        Your key. The current one is never shown; leave it empty to keep it.
        ↑ ↓ row · ← → set · enter save · esc back

    The names are on the left and the values on the right: a typed row is an editor on a band, a switch is the rail
    ``/statusline`` uses, with its knob, and a choice is its words with the chosen one marked. Up, Down and Tab move
    between rows (they are no use inside a one-line editor), Left and Right and Space set a switch or a choice, and
    Enter saves every row at once, as a form does: the answers go to ``on_save``, which answers ``None`` when it took
    them or ``(key, sentence)`` when it did not. The sentence is shown under the title and the cursor goes to the row it
    names, with every row as typed. The two actions at the bottom take the answers along when ``saves`` says so, and the
    page scrolls when the screen is too short for every row.

    Args:
        title: The model's name.
        settings: The rows, top to bottom.
        actions: The things to do with the model, under the rows.
        on_save: Receives the answers when Enter is pressed on a setting.
        on_action: Receives the action chosen and the answers.
        on_cancel: Called on Escape.
    """

    KEYS = f"{ARROW_UP} {ARROW_DOWN} row {SEPARATOR} \u2190 \u2192 set {SEPARATOR} enter save {SEPARATOR} esc back"

    def __init__(
        self,
        title: str,
        settings: Sequence[Setting],
        actions: Sequence[Action] = (),
        *,
        on_save: Callable[[dict[str, Answer]], tuple[str, str] | None],
        on_action: Callable[[Action, dict[str, Answer]], tuple[str, str] | None],
        on_cancel: Callable[[], None],
    ) -> None:
        """Build the rows with the cursor in the first."""
        super().__init__()
        if not settings:
            raise ValueError("A model page needs at least one setting")
        self.title = title
        self.settings = tuple(settings)
        self.on_save = on_save
        self.on_action = on_action
        self.on_cancel = on_cancel
        #: Why the last save was refused; empty until one is, and again as soon as the reader changes a row.
        self.refusal = ""
        #: The first visible slot of the list, so a screen too short for it still shows the row the cursor is in.
        self.top = 0
        self._rows: dict[str, _Row] = {}
        slots: list[_Row | None] = []
        for setting in self.settings:
            row: _Row = _TextRow(self, setting) if setting.kind in ("text", "secret") else _RailRow(self, setting)
            self._rows[setting.key] = row
            slots.append(row)
        if actions:
            slots.append(None)  # a blank row between the settings and what can be done with them
        for action in actions:
            row = _ActionRow(self, action)
            self._rows[action.key] = row
            slots.append(row)
        self._slots: list[_Row | None] = slots
        self._order: list[_Row] = [slot for slot in slots if slot is not None]
        self._start = self.values

    # -- tree ------------------------------------------------------------------------
    @property
    def children(self) -> tuple[Widget, ...]:
        """Expose every row, whether it is on screen or not."""
        return tuple(self._order)

    @property
    def focusable(self) -> bool:
        """Leave the cursor to the rows."""
        return False

    # -- the answers -----------------------------------------------------------------
    @property
    def values(self) -> dict[str, Answer]:
        """Return every setting's answer by key."""
        answers: dict[str, Answer] = {}
        for setting in self.settings:
            row = self._rows[setting.key]
            if isinstance(row, (_TextRow, _RailRow)):
                answers[setting.key] = row.answer
        return answers

    @property
    def changed(self) -> bool:
        """Return whether any row is anything but how it started."""
        return self.values != self._start

    def edited(self) -> None:
        """Forget the refusal once the reader starts correcting it."""
        self.refusal = ""

    def editor(self, key: str) -> LineArea:
        """Return the editor of a typed row.

        Raises:
            KeyError: When the key is not a typed row's.
        """
        row = self._rows.get(key)
        if not isinstance(row, _TextRow):
            raise KeyError(key)
        return row.area

    def focus_key(self) -> str | None:
        """Return the key of the row the cursor is in, if it is in one."""
        return next((key for key, row in self._rows.items() if row.here), None)

    # -- geometry --------------------------------------------------------------------
    def _view(self) -> int:
        """Return how many rows of the list the panel has room for."""
        return max(1, self.rect.height - CHROME_ROWS)

    def _reveal(self) -> None:
        """Scroll the list the least that shows the row the cursor is in."""
        view = self._view()
        here = next((index for index, row in enumerate(self._slots) if row is not None and row.here), None)
        if here is not None:
            if here < self.top:
                self.top = here
            if here >= self.top + view:
                self.top = here - view + 1
        self.top = max(0, min(self.top, len(self._slots) - view))

    def _place(self) -> None:
        """Give the rows on screen a line each, and the others none."""
        for hidden in self._order:
            hidden.layout(Rect(self.rect.x, self.rect.y, 0, 0))
        first = self.rect.y + 2
        for offset, slot in enumerate(self._slots[self.top : self.top + self._view()]):
            if slot is not None:
                slot.layout(Rect(self.rect.x, first + offset, self.rect.width, 1))

    def layout(self, rect: Rect) -> None:
        """Place the rows that fit."""
        super().layout(rect)
        self._reveal()
        self._place()

    # -- painting --------------------------------------------------------------------
    def render(self, canvas: Canvas) -> None:
        """Fill the panel, then draw the title, the refusal, the rows on screen, the explanation and the keys."""
        if self.rect.empty:
            return
        theme = self.theme
        surface = theme.surface_alt
        canvas.fill(self.rect.x, self.rect.y, self.rect.width, self.rect.height, Style(background=surface))
        self._reveal()
        self._place()
        x = self.rect.x + MARGIN
        room = max(0, self.rect.width - 2 * MARGIN)
        muted = Style(foreground=theme.muted, background=surface)
        canvas.draw_text(
            x, self.rect.y, truncate(self.title, room), Style(foreground=theme.text, background=surface, bold=True)
        )
        if self.changed:
            tag = "edited"
            start = self.rect.right - MARGIN - display_width(tag)
            if start > x + display_width(self.title) + 2:
                canvas.draw_text(start, self.rect.y, tag, Style(foreground=theme.accent, background=surface, bold=True))
        if self.refusal:
            canvas.draw_text(
                x,
                self.rect.y + 1,
                truncate(self.refusal, room),
                Style(foreground=theme.warning, background=surface),
                max_width=room,
            )
        for row in self._order:
            row.render(canvas)
        # A mark at the edge says there is more list than the screen could give it.
        first = self.rect.y + 2
        if self.top > 0:
            canvas.draw_text(self.rect.right - MARGIN, first, "\u25b2", muted)
        if self.top + self._view() < len(self._slots):
            canvas.draw_text(self.rect.right - MARGIN, first + self._view() - 1, "\u25bc", muted)
        canvas.draw_text(x, self.rect.bottom - 2, truncate(self._explanation(), room), muted, max_width=room)
        canvas.draw_text(x, self.rect.bottom - 1, truncate(self.KEYS, room), muted, max_width=room)

    def _explanation(self) -> str:
        """Return the sentence about the row the cursor is in, or nothing when it is in none."""
        key = self.focus_key()
        return "" if key is None else self._rows[key].hint

    def cursor(self) -> Point | None:
        """Forward the cursor of the editor that has it."""
        for row in self._order:
            if isinstance(row, _TextRow) and row.here:
                return row.cursor()
        return None

    # -- keys ------------------------------------------------------------------------
    def refuse(self, host: Host, key: str, reason: str) -> None:
        """Say why nothing was saved and put the cursor where it can be fixed."""
        self.refusal = reason
        row = self._rows.get(key)
        if row is not None:
            host.focus(row.target)

    def _required(self, host: Host) -> bool:
        """Refuse, and say so, when a required row is empty; return whether the page was refused."""
        values = self.values
        for setting in self.settings:
            if setting.required and not values[setting.key]:
                self.refuse(host, setting.key, f"{setting.label.lower()} is required")
                return True
        return False

    def save(self, host: Host) -> None:
        """Save every row, unless a required one is empty or the owner refuses."""
        if self._required(host):
            return
        refused = self.on_save(self.values)
        if refused is not None:
            self.refuse(host, *refused)

    def act(self, action: Action, host: Host) -> None:
        """Do one of the actions, with the rows' answers when it takes them."""
        if action.saves and self._required(host):
            return
        refused = self.on_action(action, self.values)
        if refused is not None:
            self.refuse(host, *refused)

    def _move(self, host: Host, step: int) -> None:
        """Put the cursor in the next or the previous row, going round at either end."""
        here = next((index for index, row in enumerate(self._order) if row.here), None)
        index = 0 if here is None else (here + step) % len(self._order)
        host.focus(self._order[index].target)
        self._reveal()
        self._place()

    def capture_event(self, event: AnyEvent, host: Host) -> bool:
        """Take Escape, Enter and the keys that move between rows before the row can."""
        key = event_key(event)
        if key == "escape":
            self.on_cancel()
            return True
        if key == "enter":
            row = next((row for row in self._order if row.here), None)
            if isinstance(row, _ActionRow):
                self.act(row.action, host)
            else:
                self.save(host)
            return True
        if key in ("tab", "down"):
            self._move(host, 1)
            return True
        if key in ("backtab", "up"):
            self._move(host, -1)
            return True
        return False

    def handle(self, event: AnyEvent, host: Host) -> bool:
        """Take the wheel over the title and the gaps, as it is taken over a row."""
        return self.bubble_event(event, host)

    def bubble_event(self, event: AnyEvent, host: Host) -> bool:
        """Move the cursor a row with the wheel, which no row has a use for."""
        if isinstance(event, MouseEvent) and self.rect.contains(event.x, event.y):
            if event.action is MouseAction.SCROLL_UP:
                self._move(host, -1)
                return True
            if event.action is MouseAction.SCROLL_DOWN:
                self._move(host, 1)
                return True
        return False


def model_settings_rows(settings: int, actions: int) -> int:
    """Return the height of a panel that shows every row: the rows, a blank before the actions, and the chrome."""
    return CHROME_ROWS + settings + (actions + 1 if actions else 0)


__all__ = ["Action", "Answer", "ModelSettingsPage", "Setting", "model_settings_rows"]
