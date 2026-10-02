"""Multi-line editor with Readline editing, history, and completion."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from ..core.events import KeyEvent, MouseAction, MouseEvent, PasteEvent, TextEvent
from ..core.geometry import Constraints, Point, Size
from ..core.host import Host
from ..core.widget import Widget
from ..render import Canvas, Style, truncate
from ..render.text import character_width, display_width
from .completion import Completer, CompletionItem

Submit = Callable[[str], bool | None]


class TextArea(Widget):
    """Edit multi-line text with the keys a terminal user already expects.

    Editing follows Emacs conventions: character and word motion, line and word
    killing, a yank buffer, undo, and submission history. Tabs are stored
    expanded so cursor movement, wrapping, and rendering share one width.

    Shape::

        > first line                       <- prompt, drawn on the first row only
          second line wraps onto more rows <- wraps at rect.width
          fourth row scrolls               <- past max_height the draft scrolls
                                              to keep the cursor row visible

    The prompt shifts only the first row (its width is ``display_width(prompt)``).
    The row count is geometry, not just paint: a draft that wraps asks the app
    for a fresh layout, which is what makes a composer grow in its box.
    """

    NEWLINE_KEYS = ("alt_enter", "shift_enter")

    def __init__(
        self,
        *,
        prompt: str = "\u203a ",
        placeholder: str = "",
        max_height: int = 7,
        completions: Sequence[str] = (),
        completer: Completer | None = None,
        history_limit: int = 200,
        on_submit: Submit | None = None,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        """Configure the prompt, history, completion source, and callbacks.

        Args:
            prompt: Drawn before the first row; its width shifts that row's text
                and the cursor, but no other row.
            placeholder: Shown in place of the first row while the draft is empty.
            max_height: Most rows the editor grows to; longer drafts scroll so the
                cursor row stays visible.
            completions: Static candidates used when no ``completer`` is given,
                matched as a prefix of the token before the cursor.
            completer: Called with ``(text, position)`` and returns the candidates
                for the token under the cursor; overrides ``completions``.
            history_limit: How many submissions to keep for Up and Ctrl-R.
            on_submit: Receives the trimmed draft on Enter; returning ``False``
                rejects it, which leaves the draft and the history untouched.
            on_change: Called after every edit that changes the draft.
        """
        super().__init__()
        self.prompt = prompt
        self.placeholder = placeholder
        self.max_height = max(1, max_height)
        self.completions = tuple(completions)
        self.completer = completer
        self.history_limit = max(1, history_limit)
        self.on_submit = on_submit
        self.on_change = on_change
        self.text = ""
        self.position = 0
        self._cursor_screen: Point | None = None
        self._kill_buffer = ""
        self._undo: list[tuple[str, int]] = []
        self._history: list[str] = []
        self._history_index: int | None = None
        self._history_draft = ""
        self._completion_state: tuple[str, tuple[CompletionItem, ...], int] | None = None

    @property
    def focusable(self) -> bool:
        """Always accept a Tab stop so the composer is ready without a click."""
        return True

    @property
    def history(self) -> tuple[str, ...]:
        """Return the submitted drafts, oldest first."""
        return tuple(self._history)

    def set_text(self, value: str) -> None:
        """Replace the draft and put the cursor at the end of it."""
        self.text = value
        self.position = len(value)
        self._leave_history()
        self._changed()

    def clear(self) -> None:
        """Reset the draft and every transient editing mode."""
        self.text = ""
        self.position = 0
        self._undo.clear()
        self._history_index = None
        self._history_draft = ""
        self._completion_state = None
        # Clearing is a draft change like any other, so an owner that mirrors
        # the draft (a completion menu) hears about it.
        self._changed()

    def completion_candidates(self) -> tuple[CompletionItem, ...]:
        """Return the candidates for the token under the cursor."""
        if self.completer is not None:
            return tuple(self.completer(self.text, self.position))
        start = self.token_start()
        token = self.text[start : self.position]
        if not token.startswith("/") or any(character.isspace() for character in token):
            return ()
        return tuple(CompletionItem(value=value) for value in self.completions if value.startswith(token))

    def token_start(self) -> int:
        """Return the index where the line under the cursor begins."""
        return self.text.rfind("\n", 0, self.position) + 1

    def preferred_height(self, width: int) -> int:
        """Return the rows the draft needs, capped at ``max_height``."""
        lines, _ = layout_input(self.text, self.position, width, self.prompt_width)
        return min(self.max_height, max(1, len(lines)))

    @property
    def prompt_width(self) -> int:
        """Return the columns the prompt reserves on the first row."""
        return display_width(self.prompt)

    def measure(self, constraints: Constraints) -> Size:
        """Claim the full offered width and the draft's height."""
        width = constraints.max_width if constraints.max_width is not None else 80
        height = self.preferred_height(max(1, width))
        return constraints.constrain(Size(width, height))

    def render(self, canvas: Canvas) -> None:
        """Paint the visible rows and remember the cell the cursor belongs on."""
        theme = self.theme
        lines, (cursor_row, cursor_column) = layout_input(self.text, self.position, self.rect.width, self.prompt_width)
        first_visible = max(0, cursor_row - self.rect.height + 1)
        body_style = Style(foreground=theme.text)
        prompt_style = Style(foreground=theme.accent_bright, bold=True)
        for local_row, line in enumerate(lines[first_visible : first_visible + self.rect.height]):
            source_row = first_visible + local_row
            x = self.rect.x + (self.prompt_width if source_row == 0 else 0)
            if source_row == 0 and self.prompt:
                canvas.draw_text(
                    self.rect.x, self.rect.y + local_row, self.prompt, prompt_style, max_width=self.rect.width
                )
            if not self.text and source_row == 0 and self.placeholder:
                canvas.draw_text(
                    x,
                    self.rect.y + local_row,
                    truncate(self.placeholder, max(0, self.rect.width - (x - self.rect.x))),
                    Style(foreground=theme.muted),
                    max_width=self.rect.width - (x - self.rect.x),
                )
                continue
            canvas.draw_text(
                x, self.rect.y + local_row, line, body_style, max_width=self.rect.width - (x - self.rect.x)
            )
        cursor_x = self.rect.x + (self.prompt_width if cursor_row == 0 else 0) + cursor_column
        self._cursor_screen = Point(cursor_x, self.rect.y + cursor_row - first_visible)

    def cursor(self) -> Point | None:
        """Show the cursor only while this editor actually has focus."""
        return self._cursor_screen if self.focused else None

    def handle(self, event, host: Host) -> bool:
        """Route a key, paste, or click to the matching editing operation."""
        if isinstance(event, MouseEvent) and self.rect.contains(event.x, event.y):
            if event.action is MouseAction.DOWN:
                host.focus(self)
                return True
            return False
        if host.focused_widget() is not self:
            return False
        if isinstance(event, (TextEvent, PasteEvent)):
            self._insert(event.text)
            return True
        if not isinstance(event, KeyEvent):
            return False
        if event.key not in ("tab", "backtab"):
            # Any other key ends the completion session, so the next Tab starts
            # a fresh cycle from the token under the cursor instead of resuming.
            self._completion_state = None
        if event.alt:
            return self._handle_alt(event.key)
        if event.key in self.NEWLINE_KEYS:
            self._insert("\n")
            return True
        match event.key:
            case "left" | "ctrl_b":
                self.position = max(0, self.position - 1)
            case "right" | "ctrl_f":
                self.position = min(len(self.text), self.position + 1)
            case "home" | "ctrl_a":
                self.position = self._line_start()
            case "end" | "ctrl_e":
                self.position = self._line_end()
            case "ctrl_home":
                self.position = 0
            case "ctrl_end":
                self.position = len(self.text)
            case "ctrl_left" | "alt_left":
                self.position = previous_word(self.text, self.position)
            case "ctrl_right" | "alt_right":
                self.position = next_word(self.text, self.position)
            case "up":
                if not self._move_vertical(-1):
                    self._move_history(-1)
            case "down":
                if not self._move_vertical(1):
                    self._move_history(1)
            case "ctrl_p":
                self._move_history(-1)
            case "ctrl_n":
                self._move_history(1)
            case "backspace":
                if self.position:
                    self._delete(self.position - 1, self.position)
            case "delete" | "ctrl_d":
                if self.position < len(self.text):
                    self._delete(self.position, self.position + 1)
            case "ctrl_w" | "alt_backspace":
                self._delete(previous_word(self.text, self.position), self.position, kill=True)
            case "ctrl_u":
                self._delete(self._line_start(), self.position, kill=True)
            case "ctrl_k":
                self._delete(self.position, self._line_end(), kill=True)
            case "ctrl_y":
                if self._kill_buffer:
                    self._insert(self._kill_buffer)
            case "ctrl_z" | "ctrl_underscore":
                self._undo_once()
            case "ctrl_g" | "escape":
                self._leave_history()
            case "ctrl_r":
                self._reverse_history_search()
            case "tab":
                self._complete(1)
            case "backtab":
                self._complete(-1)
            case "enter":
                self._submit()
            case _:
                return False
        return True

    def _submit(self) -> None:
        """Offer the trimmed draft to the submit hook, recording it when accepted."""
        value = self.text.strip()
        if not value:
            return
        if self.on_submit is not None and self.on_submit(value) is False:
            return
        if not self._history or self._history[-1] != value:
            self._history.append(value)
            del self._history[: -self.history_limit]
        self.clear()

    def _insert(self, value: str) -> None:
        """Insert text at the cursor, expanding tabs and recording undo."""
        if not value:
            return
        value = value.expandtabs(4)
        self._remember_undo()
        self._leave_history()
        self.text = self.text[: self.position] + value + self.text[self.position :]
        self.position += len(value)
        self._changed()

    def _handle_alt(self, key: str) -> bool:
        """Handle the Alt-key motion and kill bindings."""
        match key.lower():
            case "b":
                self.position = previous_word(self.text, self.position)
            case "f":
                self.position = next_word(self.text, self.position)
            case "d":
                self._delete(self.position, next_word(self.text, self.position), kill=True)
            case "<":
                self.position = 0
            case ">":
                self.position = len(self.text)
            case _:
                return False
        return True

    def _line_start(self) -> int:
        """Return the index just after the previous newline."""
        return self.text.rfind("\n", 0, self.position) + 1

    def _line_end(self) -> int:
        """Return the next newline, or the end of the text."""
        end = self.text.find("\n", self.position)
        return len(self.text) if end < 0 else end

    def _move_vertical(self, direction: int) -> bool:
        """Move one row up or down, keeping the column, and report whether it moved."""
        start = self._line_start()
        column = self.position - start
        if direction < 0:
            if start == 0:
                return False
            previous_end = start - 1
            previous_start = self.text.rfind("\n", 0, previous_end) + 1
            self.position = min(previous_start + column, previous_end)
            return True
        end = self._line_end()
        if end == len(self.text):
            return False
        next_start = end + 1
        next_end = self.text.find("\n", next_start)
        if next_end < 0:
            next_end = len(self.text)
        self.position = min(next_start + column, next_end)
        return True

    def _delete(self, start: int, end: int, *, kill: bool = False) -> None:
        """Remove a range, optionally storing the removed text in the kill buffer.

        Args:
            start: First index to remove, clamped to the draft.
            end: Index to stop before, clamped as well; an empty range does nothing.
            kill: Store the removed text so Ctrl-Y can yank it back.
        """
        start, end = max(0, start), min(len(self.text), end)
        if start >= end:
            return
        self._remember_undo()
        removed = self.text[start:end]
        if kill:
            self._kill_buffer = removed
        self.text = self.text[:start] + self.text[end:]
        self.position = start
        self._leave_history()
        self._changed()

    def _remember_undo(self) -> None:
        """Push the current state onto the undo stack, skipping duplicates."""
        state = (self.text, self.position)
        if not self._undo or self._undo[-1] != state:
            self._undo.append(state)
            del self._undo[:-100]

    def _undo_once(self) -> None:
        """Restore the most recent undo state."""
        if self._undo:
            self.text, self.position = self._undo.pop()
            self._leave_history()
            self._changed()

    def _move_history(self, direction: int) -> None:
        """Walk the submission history, restoring the draft when stepping past the end.

        Args:
            direction: ``-1`` walks back to older entries, ``1`` forward toward
                the live draft.
        """
        if not self._history:
            return
        if self._history_index is None:
            if direction > 0:
                return
            self._history_draft = self.text
            self._history_index = len(self._history) - 1
        else:
            next_index = self._history_index + direction
            if next_index >= len(self._history):
                self.text = self._history_draft
                self.position = len(self.text)
                self._history_index = None
                self._changed()
                return
            self._history_index = max(0, next_index)
        self.text = self._history[self._history_index]
        self.position = len(self.text)
        self._changed()

    def _leave_history(self) -> None:
        """Stop browsing history so the next edit starts a fresh draft."""
        self._history_index = None

    def _reverse_history_search(self) -> None:
        """Jump to the newest history entry containing the current text."""
        if not self._history:
            return
        query = self.text if self._history_index is None else self._history_draft
        start = len(self._history) if self._history_index is None else self._history_index
        match = next((index for index in range(start - 1, -1, -1) if query in self._history[index]), None)
        if match is None:
            return
        if self._history_index is None:
            self._history_draft = query
        self._history_index = match
        self.text = self._history[match]
        self.position = len(self.text)
        self._changed()

    def _complete(self, direction: int) -> None:
        """Cycle the token under the cursor through its completion candidates.

        Args:
            direction: ``1`` for Tab, ``-1`` for Shift-Tab; both wrap around the
                candidate list.
        """
        state = self._completion_state
        if state is None:
            candidates = self.completion_candidates()
            if not candidates:
                return
            token = self.text[self.token_start() : self.position]
            # The first Tab must land on the first candidate, so the stored index
            # starts one step behind it.
            state = (token, candidates, -1 if direction > 0 else 0)
        original, candidates, index = state
        index = (index + direction) % len(candidates)
        start = self.text.rfind("\n", 0, self.position) + 1
        current = self.text[start : self.position]
        self._remember_undo()
        value = candidates[index].value
        self.text = self.text[:start] + value + self.text[self.position :]
        self.position += len(value) - len(current)
        self._completion_state = (original, candidates, index)
        self._changed()

    def _changed(self) -> None:
        """Repaint the editor, re-layout when it grew, and tell the owner.

        The row count is geometry, not just paint: a draft that wraps onto
        another row needs the boxes around this editor to split their space
        again, so the app is asked for a fresh layout whenever the height at the
        current width changes. Keystrokes that stay on the same rows only
        repaint.
        """
        self.invalidate()
        if self.app is not None and self.preferred_height(max(1, self.rect.width)) != self.rect.height:
            self.app.request_layout()
        if self.on_change is not None:
            self.on_change()


def previous_word(value: str, position: int) -> int:
    """Return the index that starts the word before position."""
    index = position
    while index and value[index - 1].isspace():
        index -= 1
    if index and word_character(value[index - 1]):
        while index and word_character(value[index - 1]):
            index -= 1
    else:
        while index and not value[index - 1].isspace() and not word_character(value[index - 1]):
            index -= 1
    return index


def next_word(value: str, position: int) -> int:
    """Return the index that ends the word after position."""
    index = position
    while index < len(value) and value[index].isspace():
        index += 1
    if index < len(value) and word_character(value[index]):
        while index < len(value) and word_character(value[index]):
            index += 1
    else:
        while index < len(value) and not value[index].isspace() and not word_character(value[index]):
            index += 1
    return index


def word_character(character: str) -> bool:
    """Return whether a character counts as part of a word."""
    return character.isalnum() or character == "_"


def layout_input(text: str, position: int, width: int, prompt_width: int) -> tuple[list[str], tuple[int, int]]:
    """Wrap editable text while preserving a source-index cursor position.

    Args:
        text: Full draft, newlines included.
        position: Cursor as a code-point index into ``text``, not a visual column.
        width: Total row width in cells.
        prompt_width: Cells the prompt occupies on the first row only.

    Returns:
        The wrapped rows and the cursor as ``(row, column)`` in cell coordinates.
    """
    width = max(1, width)
    rows = [""]
    row = 0
    column = 0
    cursor = (0, 0)
    for index, character in enumerate(text):
        if index == position:
            available = max(1, width - (prompt_width if row == 0 else 0))
            cursor = (row + 1, 0) if column >= available else (row, column)
        if character == "\n":
            rows.append("")
            row += 1
            column = 0
            continue
        char_width = character_width(character)
        available = max(1, width - (prompt_width if row == 0 else 0))
        if column and column + char_width > available:
            rows.append("")
            row += 1
            column = 0
        rows[row] += character
        column += char_width
    if position == len(text):
        available = max(1, width - (prompt_width if row == 0 else 0))
        if column >= available:
            rows.append("")
            cursor = (row + 1, 0)
        else:
            cursor = (row, column)
    return rows, cursor
