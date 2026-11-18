"""Unified diff parsing with word-level emphasis."""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
from difflib import unified_diff as _unified_diff

from ..core.geometry import Constraints, Size
from ..core.widget import Widget
from ..render import Canvas, Style
from ..render.text import display_width

HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
TOKEN = re.compile(r"\w+|\s+|[^\w\s]")
META_PREFIXES = ("diff ", "index ", "--- ", "+++ ", "\\ No newline", "old mode", "new mode", "similarity index")


@dataclass(frozen=True, slots=True)
class DiffSegment:
    """One run of a diff line, marked when it is what actually changed."""

    text: str
    emphasis: bool = False


@dataclass(frozen=True, slots=True)
class DiffLine:
    """One rendered diff row in unified-diff order."""

    kind: str
    text: str
    segments: tuple[DiffSegment, ...] = ()
    old_number: int | None = None
    new_number: int | None = None


def _pair(removals: Sequence[object], additions: Sequence[object]) -> Iterator[tuple[int, int]]:
    """Yield the positions of a run of removals and the additions that answer them, paired in order.

    The first removal is paired with the first addition, and so on; the longer run keeps its rest as rows
    with nothing to be compared with. The rule is written once, here, so a unified diff and a tool call's
    rows cannot pair differently; the lengths are the lists' own, so a pair cannot name a row that is not
    there.
    """
    return zip(range(len(removals)), range(len(additions)), strict=False)


def paired_rows(rows: Iterable[tuple[str, str]]) -> list[tuple[str, tuple[DiffSegment, ...]]]:
    """Pair a run of removals with the additions that follow it, token by token.

    A change is stored as rows of ``(sign, text)``: ``"-"`` a line taken away, ``"+"`` the line put in
    its place, and any other sign a row with nothing to pair. Removals are paired with the additions
    right after them by position, which is what makes a rewritten line readable: only the tokens that
    differ are marked, so a one-word change shows which word it is instead of one whole line against
    another.

    A row with no opposite is a single unmarked run. A line that was added whole *is* the change, so
    marking all of it would say no more than the band behind it already says; a row is marked only
    where it has a row to be compared with. A :class:`DiffView` marks such a row whole instead, because
    its rows have no band of their own to lean on.

    Args:
        rows: The rows in the order they are drawn.

    Returns:
        One ``(sign, segments)`` per row, in the same order.
    """
    paired: list[tuple[str, tuple[DiffSegment, ...]]] = []
    removals: list[tuple[int, str]] = []
    additions: list[tuple[int, str]] = []

    def flush() -> None:
        """Mark the tokens that differ between the buffered removals and the additions after them."""
        for old_index, new_index in _pair(removals, additions):
            old_row, old_text = removals[old_index]
            new_row, new_text = additions[new_index]
            old_segments, new_segments = word_diff(old_text, new_text)
            paired[old_row] = (paired[old_row][0], old_segments)
            paired[new_row] = (paired[new_row][0], new_segments)
        removals.clear()
        additions.clear()

    for sign, text in rows:
        if sign == "-":
            if additions:
                flush()  # a removal closes the additions before it, so the run it joins starts clean
            removals.append((len(paired), text))
        elif sign == "+":
            additions.append((len(paired), text))
        else:
            flush()
        paired.append((sign, (DiffSegment(text),)))
    flush()
    return paired


def word_diff(old: str, new: str) -> tuple[tuple[DiffSegment, ...], tuple[DiffSegment, ...]]:
    """Return both sides tokenized, marking the tokens that differ.

    Args:
        old: Text of the removed line.
        new: Text of the added line it is paired with.
    """
    old_tokens = TOKEN.findall(old)
    new_tokens = TOKEN.findall(new)
    matcher = SequenceMatcher(None, old_tokens, new_tokens, autojunk=False)
    old_segments: list[DiffSegment] = []
    new_segments: list[DiffSegment] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        changed = tag != "equal"
        old_segments.append(DiffSegment("".join(old_tokens[i1:i2]), changed))
        new_segments.append(DiffSegment("".join(new_tokens[j1:j2]), changed))
    return _merge(old_segments), _merge(new_segments)


def parse_unified(text: str) -> list[DiffLine]:
    """Parse unified-diff text, pairing removals with additions by position."""
    lines: list[DiffLine] = []
    removals: list[DiffLine] = []
    additions: list[DiffLine] = []
    old_number: int | None = None
    new_number: int | None = None

    def flush() -> None:
        """Pair buffered removals with additions, then emit both blocks."""
        nonlocal removals, additions
        if not removals and not additions:
            return
        for old_index, new_index in _pair(removals, additions):
            old_segments, new_segments = word_diff(removals[old_index].text, additions[new_index].text)
            removals[old_index] = replace(removals[old_index], segments=old_segments)
            additions[new_index] = replace(additions[new_index], segments=new_segments)
        for line in removals:
            lines.append(line if line.segments else replace(line, segments=(DiffSegment(line.text, True),)))
        for line in additions:
            lines.append(line if line.segments else replace(line, segments=(DiffSegment(line.text, True),)))
        removals, additions = [], []

    for raw in text.splitlines():
        if raw.startswith(META_PREFIXES):
            flush()
            lines.append(DiffLine("meta", raw))
            continue
        hunk = HUNK.match(raw)
        if hunk:
            flush()
            old_number = int(hunk.group(1))
            new_number = int(hunk.group(3))
            lines.append(DiffLine("hunk", raw))
            continue
        if raw.startswith("+"):
            additions.append(DiffLine("add", raw[1:], new_number=new_number))
            new_number = None if new_number is None else new_number + 1
            continue
        if raw.startswith("-"):
            removals.append(DiffLine("remove", raw[1:], old_number=old_number))
            old_number = None if old_number is None else old_number + 1
            continue
        flush()
        content = raw[1:] if raw.startswith(" ") else raw
        lines.append(DiffLine("context", content, old_number=old_number, new_number=new_number))
        old_number = None if old_number is None else old_number + 1
        new_number = None if new_number is None else new_number + 1
    flush()
    return lines


def build_unified(
    old: str,
    new: str,
    *,
    fromfile: str = "a",
    tofile: str = "b",
    context: int = 3,
) -> list[DiffLine]:
    """Diff two texts and return parsed diff rows.

    Args:
        old: Original text; trailing newlines are ignored.
        new: Replacement text.
        fromfile: Label of the original side in the ``---`` header line.
        tofile: Label of the replacement side in the ``+++`` header line.
        context: Unchanged lines kept around each hunk.
    """
    # difflib appends its own terminator to header lines, so the terminator has
    # to be suppressed before joining: a stray blank line would otherwise parse
    # as a context row and shift every following line number.
    text = "\n".join(_unified_diff(old.splitlines(), new.splitlines(), fromfile, tofile, n=context, lineterm=""))
    return parse_unified(text)


class DiffView(Widget):
    """Paint unified-diff rows with a gutter and word-level emphasis.

    Shape::

                 --- a
                 +++ b
                 @@ -1,5 +1,2 @@          <- hunk headers, dim
          1    1  def total(items):      <- old and new line numbers
          2       -    value = 0          <- removed
               2  +    return sum(...)    <- added

    The gutter is reserved only when the diff carries line numbers. Removed and
    added lines are paired by position, and only the tokens that actually differ
    get the deeper band (:attr:`Theme.addition_emphasis_fill` and
    :attr:`Theme.deletion_emphasis_fill`), which is what makes a one-word change
    readable.
    """

    def __init__(self, lines: tuple[DiffLine, ...] | list[DiffLine] = ()) -> None:
        """Store the diff rows; the widget itself only paints them.

        Args:
            lines: Rows in unified-diff order, as ``parse_unified`` returns them.
        """
        super().__init__()
        self.lines = tuple(lines)

    @classmethod
    def from_text(cls, text: str) -> DiffView:
        """Build a view from unified-diff text."""
        return cls(parse_unified(text))

    @classmethod
    def between(cls, old: str, new: str, *, context: int = 3) -> DiffView:
        """Diff two texts with difflib and wrap the result.

        Args:
            old: Original text; trailing newlines are ignored.
            new: Replacement text.
            context: Unchanged lines kept around each hunk.
        """
        return cls(build_unified(old, new, context=context))

    @property
    def gutter(self) -> int:
        """Reserve line numbers only when the diff actually carries them."""
        if any(line.old_number is not None or line.new_number is not None for line in self.lines):
            return 11
        return 0

    def measure(self, constraints: Constraints) -> Size:
        """Ask for the widest row plus the gutter and the sign column."""
        widest = max((display_width(line.text) + self.gutter + 1 for line in self.lines), default=0)
        return constraints.constrain(Size(widest, len(self.lines)))

    def render(self, canvas: Canvas) -> None:
        """Paint each row with its line numbers, sign, and emphasised segments."""
        if self.rect.empty:
            return
        theme = self.theme
        styles = {
            "add": Style(foreground=theme.addition, bold=True),
            "remove": Style(foreground=theme.deletion, bold=True),
            "hunk": Style(foreground=theme.accent_bright, dim=True),
            "meta": Style(foreground=theme.muted, dim=True),
            "context": Style(foreground=theme.subtle),
        }
        # The rows a change is made of, and the words within them that it rewrote: the same two bands the
        # transcript's diff sits on, so "the words that changed" reads the same everywhere in the program.
        marked = {
            "add": replace(styles["add"], background=theme.addition_emphasis_fill),
            "remove": replace(styles["remove"], background=theme.deletion_emphasis_fill),
        }
        gutter = self.gutter
        limit = self.rect.x + self.rect.width
        for row, line in enumerate(self.lines[: self.rect.height]):
            y = self.rect.y + row
            x = self.rect.x
            style = styles.get(line.kind, styles["context"])
            if gutter:
                old = "" if line.old_number is None else str(line.old_number)
                new = "" if line.new_number is None else str(line.new_number)
                x += canvas.draw_text(
                    x,
                    y,
                    f"{old:>4} {new:>4} ",
                    Style(foreground=theme.muted, dim=True),
                    max_width=gutter,
                )
            sign = {"add": "+", "remove": "-", "context": " "}.get(line.kind, " ")
            x += canvas.draw_text(x, y, sign, style, max_width=max(0, limit - x))
            segments = line.segments or (DiffSegment(line.text),)
            for segment in segments:
                if x >= limit:
                    break
                segment_style = marked.get(line.kind, style) if segment.emphasis else style
                x += canvas.draw_text(x, y, segment.text, segment_style, max_width=limit - x)


def _merge(segments: list[DiffSegment]) -> tuple[DiffSegment, ...]:
    """Join adjacent runs that share an emphasis flag."""
    merged: list[DiffSegment] = []
    for segment in segments:
        if not segment.text:
            continue
        if merged and merged[-1].emphasis == segment.emphasis:
            merged[-1] = DiffSegment(merged[-1].text + segment.text, segment.emphasis)
        else:
            merged.append(segment)
    return tuple(merged)
