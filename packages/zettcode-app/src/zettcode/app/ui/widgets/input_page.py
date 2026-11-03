"""The bottom panel that asks for one line of text: an address, a model id, a token."""

from __future__ import annotations

from collections.abc import Callable

from zettcode.tui import (
    PROMPT,
    SEPARATOR,
    AnyEvent,
    Canvas,
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

#: What stands in for each character of a secret, so the reader sees that something was typed.
MASK = "\u2022"

#: The rows the panel takes: the title, up to three lines of help, the note, the line itself and the keys.
INPUT_ROWS = 7


class SecretArea(TextArea):
    """A :class:`TextArea` that paints a bullet for every character instead of the character.

    Only the painting is changed. The text, the cursor and the editing keys are the editor's own, so
    a paste, Backspace and Ctrl-U work as they do anywhere, and what is submitted is what was typed.
    A token is ASCII, so a bullet is as wide as the character it hides and the cursor stays under it.
    """

    def spans_for(self, line: str, start: int, body: Style) -> tuple[Span, ...]:
        """Paint the row as bullets."""
        return (Span(MASK * len(line), body),)


class InputPage(VBox):
    """Ask for one line, say what it is for, and refuse an answer that will not do.

    Shape::

        Token for DeepSeek
        The key from platform.deepseek.com; it is written to ~/.zettcode/config.toml.
        ● that is not an address               <- why the last answer was refused
        › ••••••••••••
        enter confirm · esc cancel

    ``on_submit`` is given the trimmed text and answers ``None`` when it took it, or a sentence
    when it did not; the sentence is shown above the line and the text stays, so a typing slip costs
    one correction rather than the whole entry.

    Args:
        title: What is being asked, in a few words.
        on_submit: Receives the trimmed answer; returns ``None`` to accept or a reason to refuse.
        on_cancel: Called on Escape.
        help_lines: Up to three short lines saying what a good answer looks like.
        secret: Paint the answer as bullets, for a token.
        initial: Text to start with, for editing something that is already set.
        placeholder: Shown while the line is empty.
        allow_empty: Accept an empty answer, which ``on_submit`` receives as ``""``.
        cancel_label: What the keys line says Escape does: "esc back" when there is a step behind.
    """

    def __init__(
        self,
        title: str,
        *,
        on_submit: Callable[[str], str | None],
        on_cancel: Callable[[], None],
        help_lines: tuple[str, ...] = (),
        secret: bool = False,
        initial: str = "",
        placeholder: str = "",
        allow_empty: bool = False,
        cancel_label: str = "esc cancel",
    ) -> None:
        """Build the panel with the line focused."""
        self.title = title
        self.help_lines = help_lines[:3]
        self.on_submit = on_submit
        self.on_cancel = on_cancel
        self.allow_empty = allow_empty
        self.note = ""
        area_type = SecretArea if secret else TextArea
        self.answer = area_type(
            prompt=f"{PROMPT} ",
            placeholder=placeholder,
            max_height=3,
            on_change=self._edited,
        )
        if initial:
            self.answer.set_text(initial)
        self._heading = RichText(self._heading_lines)
        self._keys = Text(f"enter confirm {SEPARATOR} {cancel_label}", muted=True)
        super().__init__(
            [
                Slot(self._heading, size=lambda width: self._heading.measure(Constraints(max_width=width)).height),
                Slot(self.answer, size=lambda width: self.answer.preferred_height(width)),
                Slot(self._keys, size=1),
            ]
        )

    def render(self, canvas: Canvas) -> None:
        """Fill the panel first: a page over the conversation owes the screen a surface.

        Without the fill whatever the frame underneath drew in these cells — the status line's
        keys, the end of a word — shows through the gaps between the panel's own text.
        """
        canvas.fill(
            self.rect.x, self.rect.y, self.rect.width, self.rect.height, Style(background=self.theme.surface_alt)
        )
        super().render(canvas)

    def _heading_lines(self) -> tuple[TextLine, ...]:
        """Return the title, the help, and the reason the last answer was refused (a blank row if none)."""
        theme = self.theme
        lines = [TextLine((Span(self.title, Style(foreground=theme.text, bold=True)),))]
        lines += [TextLine((Span(line, Style(foreground=theme.muted)),)) for line in self.help_lines]
        lines.append(TextLine((Span(self.note, Style(foreground=theme.warning)),)) if self.note else TextLine())
        return tuple(lines)

    def _edited(self) -> None:
        """Forget the reason once the reader starts correcting it."""
        self.note = ""

    @property
    def text(self) -> str:
        """Return what is typed, trimmed."""
        return self.answer.text.strip()

    def _submit(self) -> bool:
        """Hand the answer on; keep it, with the reason, when it is refused. Never clears the line."""
        value = self.text
        if not value and not self.allow_empty:
            self.note = "type something, or Esc to cancel"
            return False
        reason = self.on_submit(value)
        if reason is not None:
            self.note = reason
        return False

    def capture_event(self, event: AnyEvent, host: Host) -> bool:
        """Take Escape and Enter before the editor can.

        Enter is taken here rather than left to the editor's own submit because the editor ignores
        an empty line, and an empty answer is sometimes the answer: it clears a setting.
        """
        key = event_key(event)
        if key == "escape":
            self.on_cancel()
            return True
        if key == "enter":
            self._submit()
            return True
        return False

    @property
    def focusable(self) -> bool:
        """Leave focus to the line inside."""
        return False

    def preferred_height(self, width: int) -> int:
        """Return how many rows the panel needs."""
        return self.measure(Constraints(max_width=width)).height


__all__ = ["INPUT_ROWS", "InputPage", "MASK", "SecretArea"]
