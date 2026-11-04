"""What a plugin implements to draw a row: the base class, and how a drawn block is cached.

A presenter turns one kind of entry into lines. The built-in ones live in `zettcode.presenters`; a plugin registers its
own through `ctx.tui.register_presenter`, and the row it draws is the same kind of object, so this — the base class and
the rule for when a row is drawn again — is part of the plugin contract, not part of the terminal.

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
        kind: The kind of entry this presenter presents; one presenter per kind.
        entry_type: The entry class this presenter is for, when it is for one family of a kind
            rather than the kind as a whole: the presenter of an edit row is the one for
            ``EditEntry``, though an edit row is a ``tool`` row like any other. The registry looks
            for the entry's own class first (and its parents') and the kind second.
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

    kind: ClassVar[EntryKind]
    entry_type: ClassVar[type[Entry] | None] = None
    gutter: ClassVar[bool] = False
    priority: ClassVar[int] = 0

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
    """The presenters of one transcript: one for each kind of entry, and for the families inside a kind.

    A presenter is found by the entry's class first, walking up its parents, and by its kind
    second. Most kinds have one presenter and no family (a notice is a notice), and ``tool`` has
    one for tools in general and one for each tool whose entry carries more than the rest.

    When more than one presenter could draw the same rows, the one with the higher
    :attr:`Presenter.priority` wins, and an equal priority goes to the later registration. That is
    what makes a transcript's own presenters the default: they are registered first, at priority 0,
    so anything a plugin registers for the same rows wins without having to outrank them.
    :meth:`replacing` appends, which is the same thing for a caller holding a registry rather than a
    plugin container.

    A presenter for a whole kind is a claim on every row of that kind, so it beats the families
    registered before it at its priority: a plugin that draws every tool row draws every tool row.
    A family registered after it, or at a higher priority, is a refinement and keeps its own.
    """

    def __init__(self, presenters: Iterable[Presenter[Any]]) -> None:
        """Register presenters in order; for one kind or class, the strongest claim wins."""
        self._by_kind: dict[EntryKind, tuple[int, int, Presenter[Any]]] = {}
        self._by_type: dict[type[Entry], tuple[int, int, Presenter[Any]]] = {}
        for order, presenter in enumerate(presenters):
            rank = (presenter.priority, order)
            if presenter.entry_type is not None:
                current = self._by_type.get(presenter.entry_type)
                if current is None or rank >= current[:2]:
                    self._by_type[presenter.entry_type] = (*rank, presenter)
            else:
                current = self._by_kind.get(presenter.kind)
                if current is None or rank >= current[:2]:
                    self._by_kind[presenter.kind] = (*rank, presenter)

    @property
    def presenters(self) -> tuple[Presenter[Any], ...]:
        """Return the presenters that draw something: the kinds' first, then the families'.

        A family a kind's presenter has outranked is left out: it would never be asked for a row.
        """
        live = [presenter for _, _, presenter in self._by_kind.values()]
        live.extend(
            presenter
            for priority, order, presenter in self._by_type.values()
            if self._by_kind.get(presenter.kind) is None or (priority, order) > self._by_kind[presenter.kind][:2]
        )
        return tuple(live)

    def replacing(self, *presenters: Presenter[Any]) -> Presenters:
        """Return a registry that draws the given kinds, and families, with the given presenters."""
        return Presenters((*self.presenters, *presenters))

    def for_entry(self, entry: Entry) -> Presenter[Any]:
        """Return the presenter for an entry: the strongest claim on its class or kind, else say so."""
        family: tuple[int, int, Presenter[Any]] | None = None
        for cls in type(entry).__mro__:
            found = self._by_type.get(cls)
            if found is not None:
                family = found
                break
        kind = self._by_kind.get(entry.kind)
        if family is not None and (kind is None or family[:2] > kind[:2]):
            return family[2]
        if kind is None:
            raise ValueError(f"No presenter for a {entry.kind.value} row")
        return kind[2]

    def lines(self, entry: Entry, width: int, theme: Theme, frame: int) -> list[TextLine]:
        """Return the rows an entry paints, rendered now and not cached."""
        return self.for_entry(entry).lines(entry, width, theme, frame)

    def block(self, entry: Entry, width: int, theme: Theme, frame: int) -> LineSource:
        """Return an entry's rows as a cached line source, in the gutter's layout."""
        return self.for_entry(entry).block(entry, width, theme, frame, self)
