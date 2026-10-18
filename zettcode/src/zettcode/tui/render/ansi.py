"""Turn the bytes a program prints into lines of styled cells: colours, carriage returns, and progress bars.

A command's output is not text, it is instructions to a terminal: ``\\x1b[31m`` turns the colour red,
``\\r`` goes back to the start of the line so the next characters overwrite it (a progress bar), ``\\x1b[K``
erases the rest of the line. A widget that showed those bytes as they are would show ``^[[31m`` all over a build
log. :class:`AnsiBuffer` is the part of a terminal that understands them, without being one: it keeps a bounded
scrollback of lines, each a row of characters with the style they were written in, and it applies the
instructions that change *what is on the line being written*. Moving the cursor up or clearing the screen would
need a grid, which a scrolling log does not have; those are dropped, and what was meant to be shown on the
current line still is.

The buffer takes text in pieces of any size: a sequence cut in half by a read is held until the rest arrives.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from .style import DEFAULT_STYLE, Span, Style
from .text import character_width

#: The sixteen colours, in the order the SGR codes 30-37 and 90-97 name them. Mid tones, chosen to stay legible on
#: both a dark and a light page: a program that prints "white" or "black" must not vanish into the background.
ANSI_COLORS: tuple[str, ...] = (
    "#6b6f76",
    "#d0504e",
    "#5fa55a",
    "#c9a227",
    "#4f8fd6",
    "#b266c4",
    "#3fa7a7",
    "#c0c4ca",
    "#8a8f98",
    "#f0716f",
    "#7fcf7a",
    "#e6c14d",
    "#6fa8e8",
    "#cf86dc",
    "#5fcfcf",
    "#f2f4f7",
)

#: Columns between tab stops.
TAB_WIDTH = 8

#: The longest escape sequence held back while waiting for its end; anything longer was never one.
MAX_PENDING = 4096

#: The levels of the colour cube's axes in the 256-colour palette.
_CUBE = (0, 95, 135, 175, 215, 255)


def xterm_color(index: int) -> str:
    """Return the colour of entry ``index`` of the 256-colour palette as ``#rrggbb``."""
    if index < 16:
        return ANSI_COLORS[index]
    if index < 232:
        index -= 16
        red, green, blue = _CUBE[index // 36], _CUBE[index // 6 % 6], _CUBE[index % 6]
    else:
        red = green = blue = 8 + (min(index, 255) - 232) * 10
    return f"#{red:02x}{green:02x}{blue:02x}"


class AnsiLine:
    """One line: its characters, and the style each was written in.

    The two lists are parallel, one entry per character, so a character can be overwritten by position (the
    carriage return) without re-slicing runs. A wide glyph is one entry; the width is worked out when a line is
    drawn or wrapped.
    """

    __slots__ = ("chars", "styles", "_width")

    def __init__(self) -> None:
        self.chars: list[str] = []
        self.styles: list[Style] = []
        self._width: int | None = None

    def __len__(self) -> int:
        return len(self.chars)

    @property
    def text(self) -> str:
        """Return the characters without their styles."""
        return "".join(self.chars)

    @property
    def width(self) -> int:
        """Return the columns the line takes up, counting wide glyphs as two."""
        if self._width is None:
            self._width = sum(map(character_width, self.chars))
        return self._width

    def put(self, column: int, character: str, style: Style) -> None:
        """Write one character at ``column``: over what is there, or after it (padding a gap with spaces)."""
        self._width = None
        if column < len(self.chars):
            self.chars[column] = character
            self.styles[column] = style
            return
        if column > len(self.chars):
            gap = column - len(self.chars)
            self.chars.extend(" " * gap)
            self.styles.extend([DEFAULT_STYLE] * gap)
        self.chars.append(character)
        self.styles.append(style)

    def truncate(self, column: int) -> None:
        """Erase from ``column`` to the end of the line."""
        if column < len(self.chars):
            del self.chars[column:]
            del self.styles[column:]
            self._width = None

    def blank(self, column: int) -> None:
        """Replace everything before ``column`` with spaces, keeping the line's length."""
        for index in range(min(column, len(self.chars))):
            self.chars[index] = " "
            self.styles[index] = DEFAULT_STYLE
        self._width = None

    def spans(self, start: int = 0, end: int | None = None) -> tuple[Span, ...]:
        """Return characters ``start`` to ``end`` as runs of one style."""
        end = len(self.chars) if end is None else min(end, len(self.chars))
        spans: list[Span] = []
        run_start = start
        for index in range(start + 1, end + 1):
            if index == end or self.styles[index] != self.styles[run_start]:
                if end > run_start:
                    spans.append(Span("".join(self.chars[run_start:index]), self.styles[run_start]))
                run_start = index
        return tuple(spans)

    def rows(self, width: int) -> list[tuple[int, int]]:
        """Return the character ranges ``(start, end)`` this line wraps into at ``width`` columns.

        An empty line is one empty row. A glyph wider than the room goes on a row of its own rather than being
        cut in half.
        """
        width = max(1, width)
        if self.width <= width:
            return [(0, len(self.chars))]
        rows: list[tuple[int, int]] = []
        start = used = 0
        for index, character in enumerate(self.chars):
            cells = character_width(character)
            if used + cells > width and index > start:
                rows.append((start, index))
                start, used = index, 0
            used += cells
        rows.append((start, len(self.chars)))
        return rows


class AnsiBuffer:
    """A bounded scrollback that understands what programs print.

    Args:
        max_lines: Most lines kept; the oldest go first.
        colors: The sixteen colours the SGR codes pick from.
    """

    def __init__(self, max_lines: int = 5000, colors: Sequence[str] = ANSI_COLORS) -> None:
        self.max_lines = max(1, max_lines)
        self.colors = tuple(colors)
        self.lines: list[AnsiLine] = [AnsiLine()]
        #: Lines dropped from the front since the buffer began, so a reader can tell the log was cut.
        self.dropped = 0
        self._column = 0
        self._pen = DEFAULT_STYLE
        self._pending = ""
        self._started = 0

    def __len__(self) -> int:
        return len(self.lines)

    @property
    def text(self) -> str:
        """Return the visible text, lines joined by newlines, without styles."""
        return "\n".join(line.text for line in self.lines)

    def clear(self) -> None:
        """Forget every line and put the pen back to the default style."""
        self.dropped += len(self.lines) - 1
        self.lines = [AnsiLine()]
        self._column = 0
        self._pen = DEFAULT_STYLE
        self._pending = ""

    def write(self, text: str, style: Style | None = None) -> int:
        """Append ``text`` and return how many lines it started.

        Args:
            text: What the program printed, escape sequences and all.
            style: The style the text is written in until its own sequences change it; the default when omitted.
                It is used only for this call, and the pen the program set is kept for the next one.
        """
        started = self._started
        saved = self._pen
        if style is not None:
            self._pen = style
        text = self._pending + text
        self._pending = ""
        index, size = 0, len(text)
        while index < size:
            character = text[index]
            if character == "\x1b":
                end = self._escape(text, index)
                if end is None:
                    self._pending = text[index:] if size - index <= MAX_PENDING else ""
                    break
                index = end
                continue
            index += 1
            if character == "\n":
                self._new_line()
            elif character == "\r":
                self._column = 0
            elif character == "\b":
                self._column = max(0, self._column - 1)
            elif character == "\t":
                for _ in range(TAB_WIDTH - self._column % TAB_WIDTH):
                    self._put(" ")
            elif character >= " " and character != "\x7f":
                self._put(character)
        if style is not None:
            self._pen = saved
        return self._started - started

    # -- one line at a time -------------------------------------------------
    def _put(self, character: str) -> None:
        self.lines[-1].put(self._column, character, self._pen)
        self._column += 1

    def _new_line(self) -> None:
        self.lines.append(AnsiLine())
        self._started += 1
        self._column = 0
        if len(self.lines) > self.max_lines:
            del self.lines[0]
            self.dropped += 1

    # -- escape sequences ---------------------------------------------------
    def _escape(self, text: str, start: int) -> int | None:
        """Apply the sequence beginning at ``start``; return where the text goes on, or ``None`` if it is cut."""
        if start + 1 >= len(text):
            return None
        kind = text[start + 1]
        if kind == "[":
            index = start + 2
            while index < len(text) and text[index] in "0123456789;:?<=>! ":
                index += 1
            if index >= len(text):
                return None
            final = text[index]
            if "@" <= final <= "~":
                self._csi(text[start + 2 : index], final)
                return index + 1
            return index  # not a sequence after all: drop the introducer and what was read
        if kind == "]":
            index = start + 2
            while index < len(text):
                if text[index] == "\x07":
                    return index + 1
                if text[index] == "\x1b":
                    return index + 2 if index + 1 < len(text) else None
                index += 1
            return None
        if kind in "()*+#%":
            return start + 3 if start + 2 < len(text) else None
        return start + 2

    def _csi(self, parameters: str, final: str) -> None:
        """Act on one control sequence: colours, and the few edits to the current line."""
        numbers = self._numbers(parameters)
        first = numbers[0] if numbers else 0
        if final == "m":
            self._sgr(numbers or [0])
        elif final == "K":
            line = self.lines[-1]
            if first == 0:
                line.truncate(self._column)
            elif first == 1:
                line.blank(self._column + 1)
            else:
                line.truncate(0)
        elif final == "G":
            self._column = max(0, (first or 1) - 1)
        elif final == "C":
            self._column += first or 1
        elif final == "D":
            self._column = max(0, self._column - (first or 1))
        elif final == "J" and first in (2, 3):
            self.clear()

    @staticmethod
    def _numbers(parameters: str) -> list[int]:
        """Read the parameters of a sequence as numbers, an empty one being 0.

        The colon form (``38:2::255:0:0``, ``4:3``) is turned into the semicolon form every program also understands: a
        colour keeps its channels and loses the empty colour-space slot, and any other sub-parameter list keeps only
        its first number, which is the attribute.
        """
        numbers: list[int] = []
        for group in parameters.split(";"):
            parts = [int(part) if part.isdigit() else 0 for part in group.split(":")]
            if len(parts) > 1 and parts[0] in (38, 48):
                if parts[1] == 2 and len(parts) >= 6:
                    parts = [parts[0], 2, *parts[-3:]]
                numbers.extend(parts)
            else:
                numbers.append(parts[0])
        return numbers

    def _sgr(self, codes: list[int]) -> None:
        """Change the pen: the "select graphic rendition" codes."""
        pen = self._pen
        index = 0
        while index < len(codes):
            code = codes[index]
            index += 1
            if code == 0:
                pen = DEFAULT_STYLE
            elif code == 1:
                pen = replace(pen, bold=True)
            elif code == 2:
                pen = replace(pen, dim=True)
            elif code == 3:
                pen = replace(pen, italic=True)
            elif code == 7:
                pen = replace(pen, reverse=True)
            elif code == 9:
                pen = replace(pen, strike=True)
            elif code == 22:
                pen = replace(pen, bold=False, dim=False)
            elif code == 23:
                pen = replace(pen, italic=False)
            elif code == 27:
                pen = replace(pen, reverse=False)
            elif code == 29:
                pen = replace(pen, strike=False)
            elif 30 <= code <= 37:
                pen = replace(pen, foreground=self.colors[code - 30])
            elif code == 39:
                pen = replace(pen, foreground=None)
            elif 40 <= code <= 47:
                pen = replace(pen, background=self.colors[code - 40])
            elif code == 49:
                pen = replace(pen, background=None)
            elif 90 <= code <= 97:
                pen = replace(pen, foreground=self.colors[code - 90 + 8])
            elif 100 <= code <= 107:
                pen = replace(pen, background=self.colors[code - 100 + 8])
            elif code in (38, 48):
                colour, index = self._extended(codes, index)
                if colour is not None:
                    pen = replace(pen, foreground=colour) if code == 38 else replace(pen, background=colour)
        self._pen = pen

    def _extended(self, codes: list[int], index: int) -> tuple[str | None, int]:
        """Read the colour after a 38 or 48: ``5;n`` for the 256-colour palette or ``2;r;g;b`` for true colour."""
        if index < len(codes) and codes[index] == 5 and index + 1 < len(codes):
            return xterm_color(codes[index + 1]) if codes[index + 1] < 256 else None, index + 2
        if index < len(codes) and codes[index] == 2:
            channels = codes[index + 1 : index + 4]
            if len(channels) == 3 and all(0 <= value < 256 for value in channels):
                return "#{:02x}{:02x}{:02x}".format(*channels), index + 4
            return None, len(codes)
        return None, len(codes)
