"""The bottom panel a question from the model appears in."""

from __future__ import annotations

from collections.abc import Callable

from ....tui import (
    DONE,
    ELLIPSIS,
    MARKER,
    PROMPT,
    SEPARATOR,
    AnyEvent,
    Canvas,
    Host,
    KeyEvent,
    RichText,
    Span,
    Style,
    Text,
    TextArea,
    TextEvent,
    TextLine,
    VBox,
    Widget,
    event_key,
)
from ....tui.core.geometry import Constraints
from ....tui.layout import Slot
from ...agent.ask import AskUserQuestion

#: Options drawn at once; a longer list scrolls around the highlight, because
#: the model may offer twenty and the panel cannot grow to fit them all.
VISIBLE_OPTIONS = 6

#: What the row that finishes a multiple-choice answer looks like.
SEND = "\u27a4 send"


def _rows(widget: Widget) -> Callable[[int], int]:
    """Return the height one child asks for at the width it is given."""
    return lambda width: widget.measure(Constraints(max_width=width)).height


class AskUserPage(VBox):
    """One question, its choices, and the line an answer can be typed into.

    Shape::

        Which format should I write the summary in?
         \u25b8 \u2713 1. Markdown                     <- checked: this is the answer
            2. Plain text
        \u203a up/down move \u00b7 enter choose \u00b7 esc cancel

    A single-choice question sends the highlighted row on ``Enter``, the way every
    other picker in the shell works. A multiple-choice one checks and unchecks
    rows instead, and grows a ``send`` row to finish with::

         \u25b8 \u2713 1. Summary
           \u2713 2. Diff
           \u27a4 send

    Under the choices sits the answer line, with no label of its own: it shows the
    keys until something is typed, and what is typed from then on. So a reader can
    pick a choice or answer in their own words — and a multiple-choice answer is
    its ticks *plus* whatever was typed beside them.

    Typing takes the panel over: the choices fold away, and the line wears the
    marker and the band the highlighted row had, because the cursor is what is
    being written then. ``Up``/``Down`` give the choices back with the text still
    in the line, and on a one-answer question no row is marked once that line
    holds words of its own — the answer is not any of the rows any more.

    Args:
        question: What the model asked, with its options.
        on_answer: Receives the trimmed answer when the reader sends it.
        on_cancel: Called when the reader presses Escape; the shell tells the
            model the question was declined.
        position: Reads this question's place among the ones waiting, as
            ``(index, total)`` at paint time; shown when the model asked several
            in one response.
    """

    def __init__(
        self,
        question: AskUserQuestion,
        *,
        on_answer: Callable[[str], None],
        on_cancel: Callable[[], None],
        position: Callable[[], tuple[int, int]] | None = None,
    ) -> None:
        """Build the panel, with the answer line focused and the first row highlighted."""
        self.question = question
        self.on_answer = on_answer
        self.on_cancel = on_cancel
        self.position = position
        self.selected = 0
        self.note = ""
        self.chosen: list[str] = []
        self._typing = False
        self.answer = TextArea(
            prompt=f"{PROMPT} ",
            placeholder=self._hint_line(),
            max_height=3,
            on_submit=lambda _text: self._submit(),
        )
        self._heading = RichText(self._question_lines)
        self._choices = RichText(self._option_lines)
        self._finish = Text(self._send_line, muted=True)
        slots = [
            Slot(self._heading, size=_rows(self._heading)),
            Slot(self._choices, size=_rows(self._choices)),
        ]
        if self._needs_send_row:
            slots.append(Slot(self._finish, size=1))
        slots.append(Slot(self.answer, size=lambda width: self.answer.preferred_height(width)))
        super().__init__(slots)

    # -- geometry -----------------------------------------------------------
    @property
    def _needs_send_row(self) -> bool:
        """Return whether the choices need a row to finish on.

        A single-choice question is finished by choosing; a multiple-choice one
        collects ticks, so it needs somewhere to say "that is all of them".
        """
        return self.question.allow_multiple and bool(self.question.options)

    def preferred_height(self, width: int) -> int:
        """Return how many rows this question needs, so the panel fits it."""
        return self.measure(Constraints(max_width=width)).height

    # -- painting -----------------------------------------------------------
    def _question_lines(self) -> tuple[TextLine, ...]:
        """Return the heading: the question, which question this is, and any note.

        The note lives here rather than under the answer line because it has to
        be readable while that line holds what the reader typed — which is
        exactly when a note like "one answer only" matters.
        """
        theme = self.theme
        heading = self.question.question
        if self.position is not None:
            index, total = self.position()
            if total > 1:
                heading = f"({index} of {total}) {heading}"
        spans = [Span(heading, Style(foreground=theme.text, bold=True))]
        tail = self.note
        if tail:
            tone = theme.warning if self.note else theme.muted
            spans.append(Span(f"  {SEPARATOR} {tail}", Style(foreground=tone)))
        return (TextLine(tuple(spans)),)

    def _option_lines(self) -> tuple[TextLine, ...]:
        """Return the choice rows, windowed around the highlight.

        While the reader is typing they are folded away, because the cursor
        belongs to what is being written then; the rows stay (blank, so the panel
        keeps its shape and the answer line stays where it is) and the first of
        them says which keys still apply.
        """
        theme = self.theme
        rows: list[TextLine] = []
        start, stop = self._window()
        if self._typing:
            folded = (1 if start > 0 else 0) + stop - start + (1 if stop < len(self.question.options) else 0)
            keys = TextLine((Span(f"  {self._keys_line()}", Style(foreground=theme.muted)),))
            return (keys, *[TextLine() for _ in range(folded - 1)])
        if start > 0:
            rows.append(TextLine((Span(f"  {ELLIPSIS} {start} above", Style(foreground=theme.muted)),)))
        for index in range(start, stop):
            highlighted = index == self.selected
            checked = self._checked(index)
            marker = f"{MARKER} " if highlighted else "  "
            # Three states read at a glance: the row the cursor is on is banded
            # strongest, a chosen one keeps a raised background of its own, and
            # the check itself carries the accent colour.
            if highlighted:
                style = Style(foreground=theme.text, background=theme.selection, bold=True)
            elif checked:
                style = Style(foreground=theme.text, background=theme.surface)
            else:
                style = Style(foreground=theme.text)
            # The box is three cells either way, so the option texts line up
            # whether or not a row is checked.
            box = Span(f"{DONE}  " if checked else "   ", Style(foreground=theme.accent, background=style.background))
            label = Span(f"{index + 1}. {self.question.options[index]}", style)
            rows.append(TextLine((Span(f" {marker}", style), box, label)))
        if stop < len(self.question.options):
            rows.append(
                TextLine(
                    (Span(f"  {ELLIPSIS} {len(self.question.options) - stop} below", Style(foreground=theme.muted)),)
                )
            )
        return tuple(rows)

    def _send_line(self) -> str:
        """Return the row that finishes a multiple-choice answer, empty while typing."""
        if self._typing:
            return ""
        picked = len(self._picked())
        marker = f"{MARKER} " if self._on_send_row else "  "
        return f" {marker}{SEND} ({picked} chosen)" if picked else f" {marker}{SEND}"

    def _keys_line(self) -> str:
        """Return the keys this question answers to."""
        if not self.question.options:
            return f"type an answer {SEPARATOR} enter sends {SEPARATOR} esc cancels"
        if self._typing:
            # The same line whichever kind of question it is: while the reader
            # writes, the panel looks the same either way.
            return f"enter sends {SEPARATOR} up/down for the choices {SEPARATOR} esc cancels"
        if self.question.allow_multiple:
            return f"up/down move {SEPARATOR} enter ticks {SEPARATOR} send finishes {SEPARATOR} esc"
        return f"up/down choose, enter sends {SEPARATOR} or type an answer {SEPARATOR} esc cancels"

    def _hint_line(self) -> str:
        """Return what the answer line shows while it is empty: the keys."""
        if self._typing:
            return f"enter sends what you typed {SEPARATOR} up/down for the choices {SEPARATOR} esc cancels"
        return self._keys_line()

    def _sync_input(self) -> None:
        """Point the answer line's prompt and placeholder at the current state.

        While the reader types, the line wears the selection marker: the choices
        have folded away, so the highlight belongs to the text being written.
        """
        self.answer.placeholder = self._hint_line()
        self.answer.prompt = f"{MARKER} " if self._typing else f"{PROMPT} "

    def render(self, canvas: Canvas) -> None:
        """Fill the panel, then paint the question, the choices, and the answer line."""
        if self.rect.empty:
            return
        # A page over the conversation owes the screen a surface: without the
        # fill, whatever the previous frame left in these cells shows through.
        canvas.fill(
            self.rect.x,
            self.rect.y,
            self.rect.width,
            self.rect.height,
            Style(background=self.theme.surface_alt),
        )
        if self._typing and not self.answer.rect.empty:
            # The row the reader is writing in is the highlighted one.
            canvas.fill(
                self.answer.rect.x,
                self.answer.rect.y,
                self.answer.rect.width,
                self.answer.rect.height,
                Style(background=self.theme.selection),
            )
        super().render(canvas)

    # -- reading the state --------------------------------------------------
    def _window(self) -> tuple[int, int]:
        """Return the slice of options to draw, keeping the highlight inside it."""
        total = len(self.question.options)
        if total <= VISIBLE_OPTIONS:
            return 0, total
        row = min(self.selected, total - 1)
        start = min(max(0, row - VISIBLE_OPTIONS + 1), total - VISIBLE_OPTIONS)
        return start, start + VISIBLE_OPTIONS

    @property
    def _on_send_row(self) -> bool:
        """Return whether the highlight is on the row that finishes the answer."""
        return self._needs_send_row and self.selected >= len(self.question.options)

    def _picked(self) -> list[str]:
        """Return the ticks the answer carries, in the order they were chosen."""
        return list(self.chosen)

    def _checked(self, index: int) -> bool:
        """Return whether an option reads as the answer.

        A ticked row follows its tick. A one-answer question has no ticks: its
        box follows the answer line — the choice ``Enter`` would make while that
        line is empty, and nothing at all once it holds words of the reader's
        own, because then the answer is not any of the rows.
        """
        option = self.question.options[index]
        if self.question.allow_multiple:
            return option in self.chosen
        written = self.answer.text.strip()
        return (written == option) if written else (index == self.selected)

    # -- input --------------------------------------------------------------
    def capture_event(self, event: AnyEvent, host: Host) -> bool:
        """Take the list keys and leave the editor everything else."""
        key = event_key(event)
        if key == "escape":
            self.on_cancel()
            return True
        if key in ("up", "down"):
            self._leave_typing()
            return self._move(-1 if key == "up" else 1, host)
        if key == "enter":
            # Typing turns the panel into an answer line: Enter then sends the
            # text, which is what a reader who just typed expects. With nothing
            # typed, Enter acts on the highlighted row, the way the shell's other
            # pickers do.
            return self._submit() if (self._typing or not self.question.options) else self._act(host)
        if self._is_typing(event):
            if not self._typing:
                self._typing = True
                self._sync_input()
                host.request_layout()
        return False

    @staticmethod
    def _is_typing(event: AnyEvent) -> bool:
        """Return whether an event is the reader writing in the answer line."""
        return isinstance(event, TextEvent) or (isinstance(event, KeyEvent) and len(event.key) == 1)

    def _leave_typing(self) -> None:
        """Give the marker back to the choices, if the reader was writing."""
        if self._typing:
            self._typing = False
            self._sync_input()

    def _move(self, step: int, host: Host) -> bool:
        """Move the highlight, stopping at both ends."""
        rows = self._row_count()
        if rows == 0:
            return False
        moved = min(max(0, self.selected + step), rows - 1) != self.selected
        self.selected = min(max(0, self.selected + step), rows - 1)
        self.note = ""
        self._sync_input()
        # The choice block is one slot whose height follows the window around
        # the highlight, so moving it is a layout change, not just a repaint.
        host.request_layout()
        return moved

    def _row_count(self) -> int:
        """Return how many rows the highlight can sit on."""
        return len(self.question.options) + (1 if self._needs_send_row else 0)

    def _act(self, host: Host) -> bool:
        """Act on the highlighted row: choose it, tick it, or finish."""
        if self._on_send_row:
            return self._submit()
        if not self.question.options:
            return False
        option = self.question.options[self.selected]
        if not self.question.allow_multiple:
            written = self.answer.text.strip()
            if written and written != option and not self.note:
                # One answer only, and the line already holds something that is
                # not this choice: say so and let the reader decide, rather than
                # throwing away what they typed on one keystroke.
                self.note = "one answer only, enter again to replace what you wrote"
                self._sync_input()
                host.request_layout()
                return True
            self.answer.set_text(option)
            self.note = ""
            self._sync_input()
            host.invalidate()
            return self._submit()
        if option in self.chosen:
            self.chosen.remove(option)
        else:
            self.chosen.append(option)
        self.note = ""
        self._sync_input()
        host.request_layout()
        return True

    def _submit(self) -> bool:
        """Send the answer, refusing an empty one.

        A multiple-choice answer is its ticks and then whatever was typed beside
        them, comma separated; a one-answer one is the line itself.
        """
        parts = [*self.chosen, self.answer.text.strip()] if self.question.allow_multiple else [self.answer.text.strip()]
        # A word typed that is already ticked is the same answer, not a second one.
        answer = ", ".join(dict.fromkeys(part for part in parts if part))
        if not answer:
            self.note = "type an answer, or choose one of the options"
            self._sync_input()
            return False
        self.on_answer(answer)
        return True
