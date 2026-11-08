"""What a plugin implements to draw a row: the base class, and how a drawn block is cached.

A presenter turns one kind of entry into lines. The built-in ones live in `zettcode.presenters`; a plugin registers its
own through `ctx.tui.register_presenter`, and the row it draws is the same kind of object, so this — the base class and
the rule for when a row is drawn again — is part of the plugin contract, not part of the terminal.

The registry (`Presenters`) is here and not with the built-in rows because `Presenter.block` takes it as its `owner`:
the base class names the registry in its own signature, so moving the registry out would make the base class import its
implementation for a type.

The two line sources here are how a block is cached: the entry keeps the last block it was drawn as, its key made of
the width, the palette, the registry and what the row looks like, so a frame that changes nothing redraws nothing.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import fields as dataclass_fields
from typing import Any, ClassVar, Generic, TypeVar

from zettcode.tui import LineSource, Span, StaticLines, Style, TextLine, Theme
from zettcode.tui.render import inset_line, layout_rich_lines, wrap_words

from .entries import Entry, EntryKind

#: Columns a row's content is inset by, past the gutter marker.
CONTENT_INDENT = 2

#: The entry a presenter accepts; each subclass pins it to one entry type.
E = TypeVar("E", bound=Entry)


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

    The type parameter is the entry the presenter handles, and :attr:`kind` is the
    kind that routes it there, so :meth:`lines` receives exactly that entry.

    Attributes:
        kind: The kind of entry this presenter claims; ``None`` means the final fallback.
        entry_type: The entry class this presenter claims, when it is for one family of a kind
            rather than the kind as a whole: the presenter of an edit row is the one for
            ``EditEntry``, though an edit row is a ``tool`` row like any other. The chain asks each
            presenter in turn: an entry class first, then the kind, then the fallback.
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

    kind: ClassVar[EntryKind | None] = None
    entry_type: ClassVar[type[Entry] | None] = None
    gutter: ClassVar[bool] = False
    priority: ClassVar[int] = 0

    def handles(self, entry: Entry) -> bool:
        """Return whether this presenter claims ``entry``.

        A family claims its entry class; a kind claims every entry of that kind; a presenter with neither is the
        fallback and claims whatever reached it.
        """
        if self.entry_type is not None:
            return isinstance(entry, self.entry_type)
        if self.kind is not None:
            return entry.kind == self.kind
        return True

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

    A presenter claims an entry with :meth:`Presenter.handles`: a family claims its entry class, a kind claims
    every entry of its kind, and a presenter with neither is the fallback. The chain is ordered by
    :attr:`Presenter.priority` and then by registration order, later first; the first claim wins. That makes a
    plugin's handler beat the built-in one without a lookup table, and lets a tool add a handler for its own
    entry class without changing the kind's presenter.
    """

    def __init__(self, presenters: Iterable[Presenter[Any]]) -> None:
        """Build the chain; a later registration wins at equal priority, and the fallback is last."""
        registered = tuple(presenters)
        self._registered = registered
        ordered = sorted(enumerate(registered), key=lambda pair: (pair[1].priority, pair[0]), reverse=True)
        self._chain: tuple[Presenter[Any], ...] = tuple(presenter for _, presenter in ordered)
        self._fallback: Presenter[Any] | None = next(
            (p for p in self._chain if p.kind is None and p.entry_type is None), None
        )
        self._by_kind: dict[EntryKind, tuple[int, int, Presenter[Any]]] = {}
        self._by_type: dict[type[Entry], tuple[int, int, Presenter[Any]]] = {}
        for order, presenter in enumerate(registered):
            rank = (presenter.priority, order)
            if presenter.entry_type is not None:
                current = self._by_type.get(presenter.entry_type)
                if current is None or rank >= current[:2]:
                    self._by_type[presenter.entry_type] = (*rank, presenter)
            elif presenter.kind is not None:
                kind = presenter.kind
                current = self._by_kind.get(kind)
                if current is None or rank >= current[:2]:
                    self._by_kind[kind] = (*rank, presenter)

    @property
    def presenters(self) -> tuple[Presenter[Any], ...]:
        """Return the presenters that draw something: the kinds' first, then the live families, fallback last."""
        live = [presenter for _, _, presenter in self._by_kind.values()]
        live.extend(
            presenter
            for priority, order, presenter in self._by_type.values()
            if presenter.kind is None
            or self._by_kind.get(presenter.kind) is None
            or (priority, order) > self._by_kind[presenter.kind][:2]
        )
        fallback = [self._fallback] if self._fallback is not None else []
        return tuple((*live, *fallback))

    def replacing(self, *presenters: Presenter[Any]) -> Presenters:
        """Return a registry that draws the given kinds, families and fallback with the given presenters."""
        return Presenters((*self._registered, *presenters))

    def for_entry(self, entry: Entry) -> Presenter[Any]:
        """Return the first presenter in the chain that claims the entry, else raise."""
        for presenter in self._chain:
            if presenter.handles(entry):
                return presenter
        raise ValueError(f"No presenter for a {entry.kind.value} row")

    def lines(self, entry: Entry, width: int, theme: Theme, frame: int) -> list[TextLine]:
        """Return the rows an entry paints, rendered now and not cached."""
        return self.for_entry(entry).lines(entry, width, theme, frame)

    def block(self, entry: Entry, width: int, theme: Theme, frame: int) -> LineSource:
        """Return an entry's rows as a cached line source, in the gutter's layout."""
        return self.for_entry(entry).block(entry, width, theme, frame, self)
