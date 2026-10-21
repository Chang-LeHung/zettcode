"""The bottom panel that asks for several lines at once: Tab moves between them and Enter saves them all."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import partial

from zettcode.tui import (
    PROMPT,
    SEPARATOR,
    AnyEvent,
    Canvas,
    HBox,
    Host,
    RichText,
    Span,
    Style,
    Text,
    TextArea,
    TextLine,
    VBox,
    event_key,
)
from zettcode.tui.core.geometry import Constraints
from zettcode.tui.layout import Slot
from zettcode.tui.render import display_width

#: What stands in for each character of a secret, so the reader sees that something was typed.
MASK = "\u2022"

#: Rows besides the fields: the title, its note, the reason a save was refused, two for the hint of the line the cursor
#: is in (it wraps rather than being cut off), and the keys.
FORM_CHROME_ROWS = 6

#: The gap between a field's label and its line, and the width of the marker that stands before the label of the line
#: the cursor is in.
LABEL_GAP = 2
MARKER_WIDTH = 2


@dataclass(frozen=True, slots=True)
class Field:
    """One line of a form.

    Attributes:
        key: What the line is called in the answers handed to the form's owner.
        label: What the reader sees beside the line.
        initial: The text it starts with.
        placeholder: Shown, muted, while the line is empty.
        hint: One sentence shown under the form while the cursor is in this line.
        required: Refuse a save while the line is empty; the label then carries a star.
        secret: Paint the line as bullets, for a token.
    """

    key: str
    label: str
    initial: str = ""
    placeholder: str = ""
    hint: str = ""
    required: bool = False
    secret: bool = False


class LineArea(TextArea):
    """A :class:`TextArea` that holds one line: no newline can be typed or pasted into it.

    A key is not a paragraph. A paste that carries the newline it was copied with (a token selected by triple click
    takes it along) would otherwise leave a second row in a field that has room for one, and the value saved with a
    line break inside it.
    """

    NEWLINE_KEYS: tuple[str, ...] = ()

    def paste(self, text: str) -> None:
        """Insert pasted text with its line breaks removed."""
        self._insert(text.replace("\r", "").replace("\n", ""))


class SecretLine(LineArea):
    """A :class:`LineArea` that paints a bullet for every character instead of the character.

    Only the painting is changed; the text, the cursor and the editing keys are the editor's own, so a paste,
    Backspace and Ctrl-U work as they do anywhere, and what is saved is what was typed.
    """

    def spans_for(self, line: str, start: int, body: Style) -> tuple[Span, ...]:
        """Paint the row as bullets."""
        return (Span(MASK * len(line), body),)


class FormPage(VBox):
    """Ask for several lines on one page, and refuse a save that will not do.

    Shape::

        Add DeepSeek
        Tab moves between the lines, Enter saves them, Esc goes back.
        ● a model id is required                     <- why the last save was refused
          Model id *   › deepseek-chat
          Token          ›
          Address        › https://api.deepseek.com
          Shown name     ›
        The id the provider calls the model, exactly as its documentation writes it.
        tab next line · enter save · esc back

    ``on_submit`` is given every line's trimmed text by key and answers ``None`` when it took them, or ``(key, sentence)``
    when it did not; the sentence is shown above the lines, the cursor goes to the line it names, and every line stays as
    typed, so a slip costs one correction rather than the whole entry.

    Args:
        title: What is being asked, in a few words.
        fields: The lines, top to bottom.
        on_submit: Receives the trimmed answers; returns ``None`` to accept or a refusal.
        on_cancel: Called on Escape.
        note: One line under the title that says how to use the form.
        cancel_label: What the keys line says Escape does.
        save_label: What the keys line says Enter does.
    """

    def __init__(
        self,
        title: str,
        fields: Sequence[Field],
        *,
        on_submit: Callable[[dict[str, str]], tuple[str, str] | None],
        on_cancel: Callable[[], None],
        note: str = "",
        cancel_label: str = "esc back",
        save_label: str = "enter save",
    ) -> None:
        """Build the form with the cursor in the first line."""
        if not fields:
            raise ValueError("A form needs at least one line")
        self.title = title
        self.fields = tuple(fields)
        self.note = note
        self.on_submit = on_submit
        self.on_cancel = on_cancel
        #: Why the last save was refused; empty until one is, and again as soon as the reader types.
        self.refusal = ""
        self.areas: dict[str, LineArea] = {}
        for field in self.fields:
            area = (SecretLine if field.secret else LineArea)(
                prompt="", placeholder=field.placeholder, max_height=1, on_change=self._edited
            )
            if field.initial:
                area.set_text(field.initial)
            self.areas[field.key] = area
        self._column = max(display_width(self._label(field)) for field in self.fields) + MARKER_WIDTH + LABEL_GAP
        self._heading = RichText(self._heading_lines)
        self._hint = RichText(self._hint_line, wrap=True)
        self._keys = Text(f"tab next line {SEPARATOR} {save_label} {SEPARATOR} {cancel_label}", muted=True)
        rows: list[Slot] = [
            Slot(self._heading, size=lambda width: self._heading.measure(Constraints(max_width=width)).height)
        ]
        for field in self.fields:
            rows.append(Slot(self._row(field), size=1))
        rows += [Slot(self._hint, size=2), Slot(self._keys, size=1)]
        super().__init__(rows)

    # -- building --------------------------------------------------------------------
    @staticmethod
    def _label(field: Field) -> str:
        return f"{field.label} *" if field.required else field.label

    def _row(self, field: Field) -> HBox:
        """Return one line of the form: its label, then the editor."""
        label = RichText(partial(self._label_line, field), wrap=False)
        return HBox([Slot(label, size=self._column), Slot(self.areas[field.key], flex=1)])

    def _label_line(self, field: Field) -> TextLine:
        """Return a label, bright and marked while the cursor is in its line."""
        theme = self.theme
        here = self.areas[field.key].focused
        marker = f"{PROMPT} " if here else "  "
        style = Style(foreground=theme.accent_bright if here else theme.muted, bold=here)
        return TextLine((Span(marker + self._label(field), style),))

    # -- painting --------------------------------------------------------------------
    def render(self, canvas: Canvas) -> None:
        """Fill the panel first: a page over the conversation owes the screen a surface.

        Without the fill whatever the frame underneath drew in these cells shows through the gaps between the panel's
        own text.
        """
        canvas.fill(
            self.rect.x, self.rect.y, self.rect.width, self.rect.height, Style(background=self.theme.surface_alt)
        )
        super().render(canvas)

    def _heading_lines(self) -> tuple[TextLine, ...]:
        """Return the title, how to use the form, and the reason the last save was refused (a blank row if none)."""
        theme = self.theme
        lines = [TextLine((Span(self.title, Style(foreground=theme.text, bold=True)),))]
        lines.append(TextLine((Span(self.note, Style(foreground=theme.muted)),)) if self.note else TextLine())
        lines.append(TextLine((Span(self.refusal, Style(foreground=theme.warning)),)) if self.refusal else TextLine())
        return tuple(lines)

    def _hint_line(self) -> TextLine:
        """Return the hint of the line the cursor is in, or nothing when it is in none."""
        for field in self.fields:
            if self.areas[field.key].focused and field.hint:
                return TextLine((Span(field.hint, Style(foreground=self.theme.muted)),))
        return TextLine()

    def _edited(self) -> None:
        """Forget the refusal once the reader starts correcting it."""
        self.refusal = ""

    # -- the answers -----------------------------------------------------------------
    @property
    def values(self) -> dict[str, str]:
        """Return every line's trimmed text by key."""
        return {key: area.text.strip() for key, area in self.areas.items()}

    def focus_key(self) -> str | None:
        """Return the key of the line the cursor is in, if it is in one."""
        return next((key for key, area in self.areas.items() if area.focused), None)

    def _refuse(self, host: Host, key: str, reason: str) -> None:
        """Say why nothing was saved and put the cursor where it can be fixed."""
        self.refusal = reason
        area = self.areas.get(key)
        if area is not None:
            host.focus(area)

    def _submit(self, host: Host) -> None:
        """Save, unless a required line is empty or the owner refuses; never clears a line."""
        values = self.values
        for field in self.fields:
            if field.required and not values[field.key]:
                self._refuse(host, field.key, f"{field.label.lower()} is required")
                return
        refused = self.on_submit(values)
        if refused is not None:
            self._refuse(host, *refused)

    def _move(self, host: Host, step: int) -> None:
        """Put the cursor in the next or the previous line, going round at either end."""
        keys = [field.key for field in self.fields]
        here = self.focus_key()
        index = (keys.index(here) + step) % len(keys) if here in keys else 0
        host.focus(self.areas[keys[index]])

    def capture_event(self, event: AnyEvent, host: Host) -> bool:
        """Take Escape, Enter and the keys that move between lines before the editor can.

        Up and Down move between lines as Tab and Shift-Tab do: in a one-line editor they have nothing else to do
        (the history of what was typed elsewhere is not wanted here).
        """
        key = event_key(event)
        if key == "escape":
            self.on_cancel()
            return True
        if key == "enter":
            self._submit(host)
            return True
        if key in ("tab", "down"):
            self._move(host, 1)
            return True
        if key in ("backtab", "up"):
            self._move(host, -1)
            return True
        return False

    @property
    def focusable(self) -> bool:
        """Leave focus to the lines inside."""
        return False

    def preferred_height(self, width: int) -> int:
        """Return how many rows the panel needs."""
        return self.measure(Constraints(max_width=width)).height


def form_rows(fields: int) -> int:
    """Return the height of a panel with this many lines."""
    return FORM_CHROME_ROWS + fields


__all__ = ["FORM_CHROME_ROWS", "Field", "FormPage", "LineArea", "SecretLine", "form_rows"]
