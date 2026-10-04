"""The composer: a text area that stands a large paste in for itself.

The editor itself is generic — it edits lines of text and knows nothing about
where they came from. This subclass adds the one thing the shell wants: a block
of code pasted from an editor should not push the rest of the draft out of view,
so a large paste is replaced by a chip that the reader can delete in one press
and that is put back when the draft is submitted.
"""

from __future__ import annotations

from collections.abc import Sequence

from ....tui import Span, Style, TextArea
from ...agent.agent import PromptPart
from ..clipboard import image_from_paste


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
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.pastes: dict[str, str] = {}
        self.images: dict[str, tuple[bytes, str]] = {}

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
        return tuple(parts)

    def attach_image(self, data: bytes, media_type: str) -> str:
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
        """Paint the chips a wrapped row covers in their own colour."""
        chip = Style(foreground=self.theme.warning, background=body.background, bold=True)
        return self._row_spans(line, start, body, chip, self._paste_ranges())

    def backspace(self) -> None:
        """Remove a whole chip — a paste or an image — when the cursor follows one."""
        chip = self._chip_before(self.position)
        if chip is None:
            super().backspace()
            return
        self._delete(self.position - len(chip), self.position)

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
        chip: Style,
        ranges: Sequence[tuple[int, int]],
    ) -> tuple[Span, ...]:
        """Split one wrapped row into body text and the chips it covers.

        A chip wider than the row is painted on each row it reaches, so a
        wrapped one still reads as a single aside.
        """
        end = start + len(line)
        spans: list[Span] = []
        cursor = start
        for chip_start, chip_end in ranges:
            if chip_end <= start or chip_start >= end:
                continue
            if chip_start > cursor:
                spans.append(Span(self.text[cursor:chip_start], body))
            overlap = (max(chip_start, start), min(chip_end, end))
            spans.append(Span(self.text[overlap[0] : overlap[1]], chip))
            cursor = overlap[1]
        if cursor < end:
            spans.append(Span(self.text[cursor:end], body))
        return tuple(spans)
