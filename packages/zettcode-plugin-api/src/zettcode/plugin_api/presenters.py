"""What a plugin implements to draw a row: the base class, and how a drawn block is cached.

A presenter turns one kind of row into lines. The built-in ones live in `zettcode.presenters`; a plugin registers its
own through `ctx.tui.register_presenter`, and the row it draws is the same kind of object, so this — the base class and
the rule for when a row is drawn again — is part of the plugin contract, not part of the terminal. A presenter takes
part in the registry's chain through its own `handle(entry, next)`: it returns itself to claim the row, or calls
`next(entry)` to leave it to the presenters after it.

The registry (`Presenters`) is here and not with the built-in rows because `Presenter.block` takes it as its `owner`:
the base class names the registry in its own signature, so moving the registry out would make the base class import its
implementation for a type.

The two line sources here are how a block is cached: the entry keeps the last block it was drawn as, its key made of
the width, the palette, the registry and what the row looks like, so a frame that changes nothing redraws nothing.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from dataclasses import fields as dataclass_fields
from typing import Any, ClassVar, Generic, TypeVar

from zettcode.tui import LineSource, Span, StaticLines, Style, TextLine, Theme
from zettcode.tui.render import inset_line, layout_rich_lines, wrap_words

from .entries import Entry

#: Columns a row's content is inset by, past the gutter marker.
CONTENT_INDENT = 2

#: The entry a presenter accepts; each subclass pins it to one entry type.
E = TypeVar("E", bound=Entry)

#: The rest of the chain: asks the presenters after this one who draws the entry.
NextPresenter = Callable[[Entry], "Presenter[Any]"]


#: The entry fields that are not part of how a row looks: its identity, and the
#: slots the cache itself lives in.
_NOT_LOOK = frozenset({"id", "block", "block_key"})


_LOOK_FIELDS: dict[type, tuple[str, ...]] = {}


def _look_fields(entry_type: type) -> tuple[str, ...]:
    """Return the names of the fields a row of this type may look different for.

    Worked out once per entry class and kept, because it is asked for every entry
    every time the transcript view measures it.
    """
    names = _LOOK_FIELDS.get(entry_type)
    if names is None:
        names = tuple(field.name for field in dataclass_fields(entry_type) if field.name not in _NOT_LOOK)
        _LOOK_FIELDS[entry_type] = names
    return names


class Presenter(Generic[E], ABC):
    """Turns one kind of entry into rows.

    The type parameter is the entry the presenter handles: :meth:`handle` claims it, then :meth:`lines` draws it.

    Attributes:
        gutter: Whether the rows open with a marker the presenter draws in the
            gutter's own column — the user's arrow, the wait row's sparkle, a
            tool's outcome. Every other row is inset past the gutter, so every
            leading glyph sits in one column and every line of content in the next.
        priority: How strongly this presenter claims the rows it draws, when more than one could draw
            them. The higher number wins, and an equal number goes to whichever was registered later,
            so the built-in presenters - priority 0, registered first - are what a transcript uses
            until a plugin registers its own. A plugin that wants to replace only some families of a
            kind, or to beat another plugin, raises this.
    """

    gutter: ClassVar[bool] = False
    priority: ClassVar[int] = 0

    @abstractmethod
    def handle(self, entry: Entry, next: NextPresenter) -> Presenter[Any]:
        """Return the presenter that draws ``entry``, handing it to ``next`` when this one does not claim it.

        This is the chain's one decision: every presenter is asked in turn, and each answers for itself. A
        presenter returns ``self`` to claim the entry, or calls ``next(entry)`` to pass it on. The registry orders
        the chain and starts it, but never matches an entry itself.
        """

    @abstractmethod
    def lines(self, entry: E, width: int, theme: Theme, frame: int) -> list[TextLine]:
        """Return the rows this entry paints at the available width."""

    def look(self, entry: E, frame: int) -> object:
        """Return what the entry's rows depend on, so unchanged ones are not drawn again.

        The default is every field of the entry. That is the safe direction to be
        wrong in: a field nobody told the cache about changes the key and costs one
        more render, where a hand-written list that forgot it would keep showing
        the row as it was. A presenter narrows it only to leave out something that
        changes without changing the rows, and adds to it only what is not a field.
        """
        return tuple(getattr(entry, name) for name in _look_fields(type(entry)))

    def block(self, entry: E, width: int, theme: Theme, frame: int, owner: Presenters) -> LineSource:
        """Return the entry's cached rows, rendering them again only when the look changed.

        Args:
            entry: The entry to present; its cache slots hold the last result.
            width: Columns available.
            theme: Palette the rows are drawn in.
            frame: Animation step, which only a presenter that animates reads.
            owner: The registry this call came through, part of the key so a
                transcript given other presenters never reuses these rows.
        """
        key: tuple[object, ...] = (width, theme, owner, self.look(entry, frame))
        if entry.block is None or entry.block_key != key:
            margin = min(CONTENT_INDENT, max(0, width - 1))
            content_width = width if self.gutter else max(1, width - margin)
            rendered = StaticLines(self.lines(entry, content_width, theme, frame))
            entry.block = rendered if self.gutter else Indented(rendered)
            entry.block_key = key
        return entry.block

    @staticmethod
    def text_lines(text: str, width: int, style: Style, *, indent: int = 0, words: bool = False) -> list[TextLine]:
        """Wrap text with the same layout used by RichText and Markdown.

        Args:
            text: What to wrap; each newline starts a new row.
            width: Columns available.
            style: The ink the text is drawn in.
            indent: Columns left empty at the start of every row.
            words: Break between words and not mid-word. For a sentence a reader is meant to read, such as an
                error naming a command to try; left off, a row breaks at the column, as code and output must.
        """
        margin = min(indent, max(0, width - 1))
        room = max(1, width - margin)
        if words:
            rows = [piece for line in text.split("\n") for piece in wrap_words(line, room)]
            # A character wider than the whole row (a wide glyph in a column or two) cannot be placed in it;
            # the layout that wraps by column cuts such a row to the budget, and so does this.
            fitted = layout_rich_lines(tuple(TextLine((Span(row, style),)) for row in rows), room, wrap=False)
            return [inset_line(row, margin) for row in fitted]
        source = tuple(TextLine((Span(line, style),)) for line in text.split("\n"))
        return [inset_line(row, margin) for row in layout_rich_lines(source, room)]


class LeadingGap(LineSource):
    """LineSource that renders one blank row before a nested source.

    Streamed answers are served by ``Markdown`` so their parsing stays
    incremental, which means the separating blank line cannot come from the
    generic presenter.
    """

    def __init__(self, source: LineSource) -> None:
        """Wrap the nested line source.

        Args:
            source: Line source whose rows shift down by one; it is a
                ``LineSource`` itself, so the wrapper stays composable.
        """
        self.source = source

    def count(self, width: int) -> int:
        """Return the nested line count plus the leading blank row."""
        return self.source.count(width) + 1

    def line(self, index: int, width: int) -> TextLine:
        """Shift the index past the blank row and delegate to the nested source."""
        if index == 0:
            return TextLine()
        return self.source.line(index - 1, width)


class Indented(LineSource):
    """LineSource that shifts every row right by a fixed margin.

    The margin is drawn with the row's own leading style, so a line that carries
    a background keeps it across the gutter. The nested source wraps at the
    remaining width, which keeps long lines inside the window instead of
    wrapping past its right edge.
    """

    def __init__(self, source: LineSource, columns: int = CONTENT_INDENT) -> None:
        """Wrap ``source`` with ``columns`` cells of leading space.

        Args:
            source: Line source to shift right.
            columns: Margin in cells; the nested source wraps that much narrower.
        """
        self.source = source
        self.columns = max(0, columns)

    def count(self, width: int) -> int:
        """Return the nested row count, which the margin does not change."""
        return self.source.count(max(1, width - self._margin(width)))

    def line(self, index: int, width: int) -> TextLine:
        """Draw the margin, then the nested row at the reduced width."""
        margin = self._margin(width)
        row = self.source.line(index, max(1, width - margin))
        return inset_line(row, margin)

    def _margin(self, width: int) -> int:
        """Keep at least one column available for content on narrow screens."""
        return min(self.columns, max(0, width - 1))


class Presenters:
    """The chain of presenters one transcript asks, strongest claim first, with a fallback last.

    Every presenter in the chain is asked through :meth:`Presenter.handle`: it decides whether it draws the entry
    and hands it to the next presenter when it does not. The chain is ordered by :attr:`Presenter.priority` and then
    by registration order, later first. The registry only starts the chain; it never matches an entry itself.
    """

    def __init__(self, presenters: Iterable[Presenter[Any]]) -> None:
        """Build the chain; a later registration wins at equal priority."""
        self._registered = tuple(presenters)
        ordered = sorted(enumerate(self._registered), key=lambda pair: (pair[1].priority, pair[0]), reverse=True)
        self._chain: tuple[Presenter[Any], ...] = tuple(presenter for _, presenter in ordered)

    @property
    def presenters(self) -> tuple[Presenter[Any], ...]:
        """Return the presenters in registration order, which is what a new registry is built from."""
        return self._registered

    @property
    def chain(self) -> tuple[Presenter[Any], ...]:
        """Return the presenters in the order the chain asks them."""
        return self._chain

    def replacing(self, *presenters: Presenter[Any]) -> Presenters:
        """Return a registry that appends the given presenters to this chain."""
        return Presenters((*self._registered, *presenters))

    def for_entry(self, entry: Entry) -> Presenter[Any]:
        """Ask the chain, presenter by presenter, which one draws the entry, else raise.

        The registry only starts the chain: each presenter's :meth:`Presenter.handle` decides whether it claims
        the entry and hands it to the next when it does not.
        """
        chain = self._chain
        if not chain:
            raise ValueError(f"No presenter for a {entry.kind.value} row")

        def ask(current: Entry, index: int) -> Presenter[Any]:
            if index == len(chain):
                raise ValueError(f"No presenter for a {current.kind.value} row")
            return chain[index].handle(current, lambda entry: ask(entry, index + 1))

        return ask(entry, 0)

    def lines(self, entry: Entry, width: int, theme: Theme, frame: int) -> list[TextLine]:
        """Return the rows an entry paints, rendered now and not cached."""
        return self.for_entry(entry).lines(entry, width, theme, frame)

    def block(self, entry: Entry, width: int, theme: Theme, frame: int) -> LineSource:
        """Return an entry's rows as a cached line source, in the gutter's layout."""
        return self.for_entry(entry).block(entry, width, theme, frame, self)
