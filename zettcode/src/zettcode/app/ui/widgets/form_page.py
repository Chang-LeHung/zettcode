"""The bottom panel that asks for several lines at once: Tab moves between them and Enter saves them all."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from zettcode.tui import (
    PROMPT,
    SEPARATOR,
    AnyEvent,
    Canvas,
    Host,
    MouseAction,
    MouseEvent,
    Rect,
    RichText,
    Span,
    Style,
    Text,
    TextArea,
    TextLine,
    VBox,
    Widget,
    event_key,
)
from zettcode.tui.core.geometry import Constraints, Point
from zettcode.tui.layout import Slot
from zettcode.tui.render import display_width

#: What stands in for each character of a secret, so the reader sees that something was typed.
MASK = "\u2022"

#: The corners and rules of a field's box.
BOX_TOP_LEFT, BOX_TOP_RIGHT = "\u256d", "\u256e"
BOX_BOTTOM_LEFT, BOX_BOTTOM_RIGHT = "\u2570", "\u256f"
BOX_HORIZONTAL, BOX_VERTICAL = "\u2500", "\u2502"

#: Rows a boxed line takes (the top border with its label, the text, the bottom border) and a bare one.
BOXED_ROWS = 3
BARE_ROWS = 1

#: Rows besides the lines: the title, the reason a save was refused, two for the hint of the line the cursor is in (it
#: wraps rather than being cut off), and the keys. A form that is given a note has one more.
FORM_CHROME_ROWS = 5

#: The gap between a bare line's label and its editor, and the width of the marker that stands before the label of
#: the line the cursor is in.
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


class FieldBox(Widget):
    """One line of a form: an editor inside a box that carries the line's label.

    Shape, boxed (three rows), the box bright and the label bold while the cursor is in it::

        ╭─ Model id * ─────────────────────────────╮
        │ deepseek-chat                         │
        ╰──────────────────────────────────────╯

    Shape, bare (one row), for a terminal too short for boxes: the label, then the editor on a band of its own::

        › Model id *   deepseek-chat

    A press anywhere on the box, its border included, puts the cursor in the editor.
    """

    def __init__(self, form: FormPage, field: Field, area: LineArea) -> None:
        """Hold one editor for one line of ``form``."""
        super().__init__()
        self.form = form
        self.field = field
        self.area = area

    @property
    def children(self) -> tuple[Widget, ...]:
        """Expose the editor."""
        return (self.area,)

    @property
    def here(self) -> bool:
        """Return whether the cursor is in this line."""
        return self.area.focused

    def layout(self, rect: Rect) -> None:
        """Put the editor inside the border, or after the label when there is no room for a border."""
        super().layout(rect)
        if self.form.boxed:
            self.area.layout(Rect(rect.x + 2, rect.y + 1, max(0, rect.width - 4), 1))
        else:
            column = self.form.column
            self.area.layout(Rect(rect.x + column, rect.y, max(0, rect.width - column), 1))

    def render(self, canvas: Canvas) -> None:
        """Draw the box and its label, or the bare label and the band, then the editor."""
        if self.rect.empty:
            return
        theme = self.theme
        label = self.form.label_of(self.field)
        if self.form.boxed:
            style = Style(foreground=theme.accent_bright if self.here else theme.muted)
            width, x, y = self.rect.width, self.rect.x, self.rect.y
            rule = BOX_HORIZONTAL * max(0, width - 2)
            canvas.draw_text(x, y, f"{BOX_TOP_LEFT}{rule}{BOX_TOP_RIGHT}", style)
            canvas.draw_text(x, y + 1, BOX_VERTICAL, style)
            canvas.draw_text(x + width - 1, y + 1, BOX_VERTICAL, style)
            canvas.draw_text(x, y + 2, f"{BOX_BOTTOM_LEFT}{rule}{BOX_BOTTOM_RIGHT}", style)
            if width > 6:
                words = Style(foreground=theme.accent_bright if self.here else theme.subtle, bold=self.here)
                canvas.draw_text(x + 2, y, f" {label} ", words, max_width=width - 4)
        else:
            marker = f"{PROMPT} " if self.here else "  "
            words = Style(foreground=theme.accent_bright if self.here else theme.muted, bold=self.here)
            canvas.draw_text(self.rect.x, self.rect.y, marker + label, words, max_width=self.form.column)
            canvas.fill(self.area.rect.x, self.area.rect.y, self.area.rect.width, 1, Style(background=theme.surface))
        self.area.render(canvas)

    def handle(self, event: AnyEvent, host: Host) -> bool:
        """Take a press on the border or the label: the editor takes one inside it for itself."""
        if isinstance(event, MouseEvent) and event.action is MouseAction.DOWN and self.rect.contains(event.x, event.y):
            host.focus(self.area)
            return True
        return False

    def cursor(self) -> Point | None:
        """Forward the editor's cursor."""
        return self.area.cursor()


class FormPage(VBox):
    """Ask for several lines on one page, and refuse a save that will not do.

    Shape::

        Add a model at DeepSeek
        ● address is required                     <- why the last save was refused
        ╭─ Model id * ─────────────────────────────╮
        │ deepseek-chat                         │
        ╰──────────────────────────────────────╯
        ╭─ Token ───────────────────────────────╮
        │                                       │
        ╰──────────────────────────────────────╯
        The id the provider calls the model, exactly as its documentation writes it.
        tab next line · enter save · esc back

    Every line is a box, bright while the cursor is in it, so it reads as something to type into. A terminal too
    short for the boxes (see :func:`form_rows`) gets one row per line instead, the editor on a band of its own.

    ``on_submit`` is given every line's trimmed text by key and answers ``None`` when it took them, or ``(key, sentence)``
    when it did not; the sentence is shown above the lines, the cursor goes to the line it names, and every line stays as
    typed, so a slip costs one correction rather than the whole entry.

    Args:
        title: What is being asked, in a few words.
        fields: The lines, top to bottom.
        on_submit: Receives the trimmed answers; returns ``None`` to accept or a refusal.
        on_cancel: Called on Escape.
        note: One line under the title that says how to use the form; none by default, because the keys line does.
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
        #: Whether the lines are drawn in boxes; decided at each layout, by whether the panel is tall enough.
        self.boxed = True
        self.areas: dict[str, LineArea] = {}
        for field in self.fields:
            area = (SecretLine if field.secret else LineArea)(
                prompt="", placeholder=field.placeholder, max_height=1, on_change=self._edited
            )
            if field.initial:
                area.set_text(field.initial)
            self.areas[field.key] = area
        #: Where a bare line's editor starts: after the marker, the longest label, and the gap.
        self.column = max(display_width(self.label_of(field)) for field in self.fields) + MARKER_WIDTH + LABEL_GAP
        self._heading = RichText(self._heading_lines)
        self._hint = RichText(self._hint_line, wrap=True)
        self._keys = Text(f"tab next line {SEPARATOR} {save_label} {SEPARATOR} {cancel_label}", muted=True)
        rows: list[Slot] = [
            Slot(self._heading, size=lambda width: self._heading.measure(Constraints(max_width=width)).height)
        ]
        for field in self.fields:
            rows.append(Slot(FieldBox(self, field, self.areas[field.key]), size=lambda width: self.line_rows))
        rows += [Slot(self._hint, size=2), Slot(self._keys, size=1)]
        super().__init__(rows)

    # -- geometry --------------------------------------------------------------------
    @property
    def line_rows(self) -> int:
        """Return the rows one line takes now: three in a box, one without."""
        return BOXED_ROWS if self.boxed else BARE_ROWS

    def layout(self, rect: Rect) -> None:
        """Choose boxes when the panel is tall enough for all of them, and lay the lines out."""
        self.boxed = rect.height >= form_rows(len(self.fields), note=bool(self.note))
        super().layout(rect)

    @staticmethod
    def label_of(field: Field) -> str:
        """Return a line's label, starred when the line is required."""
        return f"{field.label} *" if field.required else field.label

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
        """Return the title, how to use the form if it says, and the reason the last save was refused (a blank row if none)."""
        theme = self.theme
        lines = [TextLine((Span(self.title, Style(foreground=theme.text, bold=True)),))]
        if self.note:
            lines.append(TextLine((Span(self.note, Style(foreground=theme.muted)),)))
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


def form_rows(fields: int, *, note: bool = False) -> int:
    """Return the height of a panel whose lines are all in boxes: three rows each, and the rows around them.

    A panel given fewer rows than this (a short terminal) draws its lines bare, one row each.
    """
    return FORM_CHROME_ROWS + (1 if note else 0) + BOXED_ROWS * fields


__all__ = ["FORM_CHROME_ROWS", "Field", "FieldBox", "FormPage", "LineArea", "SecretLine", "form_rows"]
