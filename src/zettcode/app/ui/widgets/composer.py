"""The composer: a text area that stands a large paste in for itself.

The editor itself is generic — it edits lines of text and knows nothing about
where they came from. This subclass adds the one thing the shell wants: a block
of code pasted from an editor should not push the rest of the draft out of view,
so a large paste is replaced by a chip that the reader can delete in one press
and that is put back when the draft is submitted.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence

from zettcode.app.agent.agent.prompt import MentionPart, PromptPart, plain_text_part
from zettcode.app.agent.dialogue.mentions import MENTION
from zettcode.tui import Canvas, KeyEvent, Point, Span, Style, TextArea
from zettcode.tui.core.events import AnyEvent
from zettcode.tui.core.host import Host
from zettcode.tui.render import display_width

from ..clipboard import image_from_paste

#: A slash command as typed: a leading ``/`` at a word boundary, then a name.
#: The lookbehind keeps a path such as ``src/foo`` from matching.
COMMAND = re.compile(r"(?<![\w/])/[a-z][a-z0-9_-]*")
#: The same tokens, anchored to the end of the text before the cursor.
MENTION_END = re.compile(MENTION.pattern + r"\Z")
COMMAND_END = re.compile(COMMAND.pattern + r"\Z")
#: The label an image chip carries, at the end of the text that was written before its picture.
IMAGE_LABEL_END = re.compile(r"\[image #\d+\]\Z")

#: What a locked composer shows in the middle of its row, and in the prompt's place when a command is being typed.
LOCK = "\U0001f512"


def _split_mentions(parts: Sequence[PromptPart]) -> tuple[PromptPart, ...]:
    """Split every text run at its ``@`` tokens, keeping the order intact."""
    split: list[PromptPart] = []
    for part in parts:
        if not isinstance(part, str):
            split.append(part)
            continue
        cursor = 0
        for match in MENTION.finditer(part):
            if match.start() > cursor:
                split.append(part[cursor : match.start()])
            split.append(MentionPart(match.group(0)))
            cursor = match.end()
        if cursor < len(part):
            split.append(part[cursor:])
    return tuple(split)


class Composer(TextArea):
    """A :class:`TextArea` whose large pastes read as a chip.

    Shape::

        > rework this [pasted text 6012 chars] please
          ^^^^^^^^^^^                           <- draft text as typed
                      ^^^^^^^^^^^^^^^^^^^^^^^^  <- chip, amber and bold; one
                                                   Backspace removes it whole

        > compare [image #1] with [image #2]
                  ^^^^^^^^^^         ^^^^^^^^^^  <- image chips, same rules

    A paste becomes a chip when it is longer than :data:`PASTE_CHIP_CHARS`
    characters or taller than the editor grows (:attr:`TextArea.max_height`
    rows), because either way it would hide the draft it was pasted into.

    Attributes:
        images: The clipboard attachments each image chip stands for, by label.
        pastes: The text each chip stands for, by chip label. A label that is no
            longer in the draft simply never matches, so editing into a chip
            turns it back into literal text; the map is only emptied when the
            draft is replaced wholesale, which is what lets an undo put a chip
            back with the text it stood for.
    """

    #: A paste longer than this many characters becomes a chip.
    PASTE_CHIP_CHARS = 512

    def __init__(self, **kwargs: object) -> None:
        """Build the editor and start with no pasted text standing in."""
        self._locked = False
        self._free_prompt = ""
        self._free_placeholder = ""
        #: Called when Enter is pressed on a locked composer with nothing typed: the reader asking to try again.
        self.on_locked_enter: Callable[[], None] | None = None
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.pastes: dict[str, str] = {}
        self.images: dict[str, tuple[bytes, str]] = {}
        #: Whether a typed ``/name`` is a command that exists, and whether a typed ``@token`` is a
        #: resource that exists. They decide what is painted as one and what Backspace takes whole:
        #: a word that merely *looks* like a command or a reference is just a word, and painting it
        #: as one tells the reader something false. Left alone they accept everything, which is
        #: what an editor that knows no commands has to do; the shell sets them.
        self.is_command: Callable[[str], bool] = lambda name: True
        self.is_mention: Callable[[str], bool] = lambda token: True
        self._hits: tuple[str, tuple[tuple[int, int, str], ...]] | None = None

    # -- locked ---------------------------------------------------------------------------------
    @property
    def locked(self) -> bool:
        """Return whether the session is another process's, so nothing can be written to it from here."""
        return self._locked

    @locked.setter
    def locked(self, value: bool) -> None:
        self._locked = value

    @property
    def prompt(self) -> str:
        """Return the arrow, or — locked — nothing, or the lock where a command being typed has its arrow."""
        if not self._locked:
            return self._free_prompt
        return f"{LOCK} " if self.text else ""

    @prompt.setter
    def prompt(self, value: str) -> None:
        self._free_prompt = value

    @property
    def placeholder(self) -> str:
        """Return the hint, which a locked composer does not give: the lock is what it shows."""
        return "" if self._locked else self._free_placeholder

    @placeholder.setter
    def placeholder(self, value: str) -> None:
        self._free_placeholder = value

    def render(self, canvas: Canvas) -> None:
        """Paint the editor; locked and empty, the lock in the middle of the row and no arrow."""
        super().render(canvas)
        if not (self._locked and not self.text) or self.rect.empty:
            return
        band = self.theme.surface_alt if self.surface else None
        banded = self.surface and self.rect.height >= 3
        inner = self.rect.height - (2 if banded else 0)
        row = self.rect.y + (1 if banded else 0) + (inner - 1) // 2
        column = self.rect.x + max(0, (self.rect.width - display_width(LOCK)) // 2)
        canvas.draw_text(column, row, LOCK, Style(foreground=self.theme.warning, background=band), max_width=2)

    def cursor(self) -> Point | None:
        """Show no cursor over the lock: there is nothing here to type into."""
        if self._locked and not self.text:
            return None
        return super().cursor()

    def handle(self, event: AnyEvent, host: Host) -> bool:
        """Edit as usual; locked, let through only what a command is made of, and make Enter a request to retry.

        What a locked draft may become is checked after the editor has acted on the key, and the draft put back
        if it may not be: every way of changing it (typing, a paste, history, undo, a completion) goes through
        here, so none needs its own guard. Deleting is always allowed, which is how a draft left over from the
        session that was left can be cleared.
        """
        if not self._locked:
            return super().handle(event, host)
        if (
            isinstance(event, KeyEvent)
            and event.key == "enter"
            and not event.alt
            and not self.text.strip()
            and host.focused_widget() is self
        ):
            if self.on_locked_enter is not None:
                self.on_locked_enter()
            return True
        before = (self.text, self.position)
        handled = super().handle(event, host)
        if self.text != before[0] and not self._allowed_when_locked(before[0], self.text):
            self.text, self.position = before
        return handled

    @staticmethod
    def _allowed_when_locked(before: str, after: str) -> bool:
        """Return whether a locked draft may change from ``before`` to ``after``: to a command, to nothing, or shorter."""
        return after == "" or after.lstrip().startswith("/") or len(after) < len(before)

    def attach_image(self, data: bytes, media_type: str) -> str:
        """Stand one clipboard image in for itself and return its chip label; a locked composer takes none."""
        if self._locked:
            return ""
        return self._attach_image(data, media_type)

    def paste(self, text: str) -> None:
        """Insert a paste: an image as a picture chip, a large block as a text chip.

        A terminal cannot paste image bytes, but some paste an image as base64
        text; that is read back into a picture so one paste key produces the
        same ``[image #N]`` chip whether the bytes came from the desktop
        clipboard or from the terminal.
        """
        if not text:
            return
        image = image_from_paste(text)
        if image is not None:
            self.attach_image(*image)
            return
        self._insert(self._remember_paste(text) if self.too_large(text) else text)

    def too_large(self, text: str) -> bool:
        """Return whether a text is too big to show in the draft as it is.

        Either dimension is enough: a long line pushes the draft sideways and a
        tall one scrolls it away, and both hide what the reader was writing.
        """
        return len(text) > self.PASTE_CHIP_CHARS or text.count("\n") + 1 > self.max_height

    @property
    def value(self) -> str:
        """Return the draft as it should be submitted, with pasted text put back."""
        value = ""
        cursor = 0
        for start, end, label in self._chip_ranges():
            value += self.text[cursor:start]
            cursor = end
            value += self.pastes.get(label, label)
        return value + self.text[cursor:]

    def parts(self) -> tuple[PromptPart, ...]:
        """Return the draft as the ordered parts of one user turn.

        Every chip is put back as what it stands for: a pasted-text chip becomes
        its text, an image chip becomes the bytes it holds. Text and images
        therefore reach the model in the order they were written — a picture
        sits where its chip sits, not after the whole prompt — and the label
        stays in front of it so the two line up. A chip that was deleted, or
        edited into something else, is simply not part of the turn.
        """
        parts: list[PromptPart] = []
        run = ""
        cursor = 0
        for start, end, label in self._chip_ranges():
            run += self.text[cursor:start]
            cursor = end
            payload = self.pastes.get(label)
            if payload is not None:
                run += payload
                continue
            image = self.images.get(label)
            if image is None:
                continue
            run += label
            if run:
                parts.append(run)
            parts.append(image)
            run = ""
        run += self.text[cursor:]
        if run:
            parts.append(run)
        return _split_mentions(parts)

    def restore(self, parts: Sequence[PromptPart]) -> None:
        """Replace the draft with a message's parts: text as it was written, pictures as chips again.

        The inverse of :meth:`parts`, for taking a message back out of a queue to edit it, or to
        hand it back after it was never sent. A picture's chip label is the last thing in the text
        before it, so it is taken off and the picture is given the next label of this draft —
        which is what keeps two messages that were both written as ``[image #1]`` from colliding
        when they are put back into one.

        Text with no picture in it goes through :meth:`set_text`, so a large block is a chip again.
        A draft with pictures is not chipped: the pictures are labels *inside* the text, and a
        chip over them would hide the labels the pictures are known by.

        Args:
            parts: The ordered parts of one or more messages, as :meth:`parts` returned them.
        """
        text = ""
        images: dict[str, tuple[bytes, str]] = {}
        for part in parts:
            if isinstance(part, (str, MentionPart)):
                text += plain_text_part(part)
                continue
            text = IMAGE_LABEL_END.sub("", text)
            label = f"[image #{len(images) + 1}]"
            images[label] = part
            text += label
        if not images:
            self.set_text(text)
            return
        self.pastes.clear()
        self.images.clear()
        TextArea.show(self, text)  # the draft as it is: no chip over the labels the pictures are known by
        self.images.update(images)
        self._leave_history()
        self._changed()

    def _attach_image(self, data: bytes, media_type: str) -> str:
        """Stand one clipboard image in for itself and return its chip label.

        Args:
            data: Encoded image bytes, exactly as the clipboard held them.
            media_type: MIME type of ``data``.

        Returns:
            The label inserted into the draft, such as ``[image #1]``.
        """
        label = f"[image #{len(self.images) + 1}]"
        self.images[label] = (data, media_type)
        self._insert(label)
        return label

    def spans_for(self, line: str, start: int, body: Style) -> tuple[Span, ...]:
        """Paint the chips, ``@`` resources, and slash commands on a row.

        The tokens are found in the draft, so a chip that was edited away simply
        stops being painted, and a mention or command is styled wherever it sits.
        """
        chip = Style(foreground=self.theme.warning, background=body.background, bold=True)
        styles = {
            "mention": Style(foreground=self.theme.accent_bright, background=body.background),
            "command": Style(foreground=self.theme.accent, background=body.background),
        }
        ranges = [(begin, end, chip) for begin, end, _ in self._chip_ranges()]
        ranges += [(begin, end, styles[kind]) for begin, end, kind in self._token_hits()]
        return self._row_spans(line, start, body, self._first_wins(ranges))

    def _token_hits(self) -> tuple[tuple[int, int, str], ...]:
        """Return the ``@`` references and slash commands in the draft that are really there.

        A reference is painted, and taken whole by Backspace, only when it names a resource that
        exists; a command only when it names one the shell has *and* it opens the draft, which is
        the one place a command is recognised at all. Everything else is ordinary text.

        Each row of the draft asks, and each ``@`` is a lookup on disk, so the answer is kept for
        as long as the draft is the same text.
        """
        if self._hits is not None and self._hits[0] == self.text:
            return self._hits[1]
        hits: list[tuple[int, int, str]] = []
        for match in MENTION.finditer(self.text):
            if self.is_mention(match.group(0)):
                hits.append((match.start(), match.end(), "mention"))
        opening = COMMAND.match(self.text.lstrip())
        if opening is not None:
            begin = len(self.text) - len(self.text.lstrip()) + opening.start()
            if self.is_command(opening.group(0)):
                hits.append((begin, begin + len(opening.group(0)), "command"))
        found = tuple(hits)
        self._hits = (self.text, found)
        return found

    @staticmethod
    def _first_wins(ranges: Sequence[tuple[int, int, Style]]) -> list[tuple[int, int, Style]]:
        """Drop overlaid ranges, keeping the earliest and widest of each start."""
        ordered = sorted(ranges, key=lambda item: (item[0], -(item[1] - item[0])))
        kept: list[tuple[int, int, Style]] = []
        cursor = 0
        for item in ordered:
            if item[0] < cursor:
                continue
            kept.append(item)
            cursor = item[1]
        return kept

    def backspace(self) -> None:
        """Remove a whole chip, ``@`` reference, or command when the cursor follows one.

        These stand for something larger than their characters — a chip for a
        paste or a picture, a token for a resource or a command — so one press
        takes the whole thing instead of peeling it apart.
        """
        chip = self._chip_before(self.position)
        if chip is None:
            token = self._token_before()
            if token is None:
                super().backspace()
                return
            chip = token
        self._delete(self.position - len(chip), self.position)

    def _token_before(self) -> str | None:
        """Return the ``@`` reference or slash command ending at the cursor, if it is a real one.

        The same test the painting uses, so what Backspace takes whole is what was painted as a
        unit: a word that was not highlighted is peeled one character at a time like any other.
        """
        for begin, end, _ in self._token_hits():
            if end == self.position:
                return self.text[begin:end]
        return None

    def show(self, value: str) -> None:
        """Replace the draft, chipping a value too large to show plainly."""
        self.pastes.clear()
        self.images.clear()
        if self.too_large(value):
            value = self._remember_paste(value)
        super().show(value)

    def clear(self) -> None:
        """Drop the draft, its pasted text, and its attachments."""
        self.pastes.clear()
        self.images.clear()
        super().clear()

    def _remember_paste(self, text: str) -> str:
        """Store one pasted payload and return the unique chip that stands for it."""
        label = f"[pasted text {len(text)} chars]"
        index = 2
        while label in self.pastes:
            label = f"[pasted text {len(text)} chars #{index}]"
            index += 1
        self.pastes[label] = text
        return label

    def _labels(self) -> tuple[str, ...]:
        """Return every chip label, the longest first so overlaps resolve sanely."""
        return tuple(sorted({*self.pastes, *self.images}, key=len, reverse=True))

    def _chip_before(self, position: int) -> str | None:
        """Return the chip label ending exactly at ``position``, if one does."""
        return next((label for label in self._labels() if self.text[:position].endswith(label)), None)

    def _paste_ranges(self) -> list[tuple[int, int]]:
        """Return the draft ranges the chips occupy, in order."""
        return [(start, end) for start, end, _ in self._chip_ranges()]

    def _chip_ranges(self) -> list[tuple[int, int, str]]:
        """Return every chip the draft still holds as ``(start, end, label)``.

        Chips are found in the draft rather than remembered, so one that was
        deleted — or edited into something else — just never matches, and undo
        brings it back by bringing its label back. Labels are scanned longest
        first and overlaps are dropped, so a short label that sits inside a
        longer one cannot cut a chip in half.
        """
        found: list[tuple[int, int, str]] = []
        for label in self._labels():
            start = self.text.find(label)
            while start >= 0:
                found.append((start, start + len(label), label))
                start = self.text.find(label, start + len(label))
        found.sort(key=lambda item: (item[0], item[0] - item[1]))
        chips: list[tuple[int, int, str]] = []
        cursor = 0
        for start, end, label in found:
            if start < cursor:
                continue
            chips.append((start, end, label))
            cursor = end
        return chips

    def _row_spans(
        self,
        line: str,
        start: int,
        body: Style,
        ranges: Sequence[tuple[int, int, Style]],
    ) -> tuple[Span, ...]:
        """Split one wrapped row into body text and the styled ranges it covers.

        A range wider than the row is painted on each row it reaches, so a
        wrapped chip still reads as a single aside.
        """
        end = start + len(line)
        spans: list[Span] = []
        cursor = start
        for range_start, range_end, style in ranges:
            if range_end <= start or range_start >= end:
                continue
            if range_start > cursor:
                spans.append(Span(self.text[cursor:range_start], body))
            overlap = (max(range_start, start), min(range_end, end))
            spans.append(Span(self.text[overlap[0] : overlap[1]], style))
            cursor = overlap[1]
        if cursor < end:
            spans.append(Span(self.text[cursor:end], body))
        return tuple(spans)
