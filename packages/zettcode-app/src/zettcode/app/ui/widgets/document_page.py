"""The page a plugin's Markdown document opens: rendered as Markdown, scrolled, closed with Escape.

A command that answers with a document rather than a line puts it here instead of into the conversation: it is a
thing to read on its own, not a message between two turns. Nothing of it joins the session or reaches the model.
"""

from __future__ import annotations

from collections.abc import Callable

from zettcode.tui import SEPARATOR, KeyEvent, Markdown, MouseAction, MouseEvent, Style, Widget

#: Rows a wheel notch moves the document.
WHEEL_ROWS = 3

#: What the footer says when the document is longer than the page.
SCROLL_HINT = f"\u2191 \u2193 scroll {SEPARATOR} esc back"

#: What it says when the whole document is already on screen: there is nothing to scroll.
SHORT_HINT = "esc back"


class DocumentPage(Widget):
    """A Markdown document from a command, drawn a screen at a time.

    Shape::

        Release notes                                  <- the title, when the command gave one
        <the document, rendered as Markdown>           <- scrolls
        ↑ ↓ scroll · esc back                          <- footer

    The text is parsed once per width and theme by :class:`zettcode.tui.Markdown`, so a long document is not
    re-rendered on every keystroke, and it is the same renderer the conversation uses, so a plugin's document looks
    like an answer rather than like a second kind of text.

    Args:
        markdown: The document, as Markdown.
        title: What the header says; the document is drawn under it.
        on_cancel: Called on Escape and ``q`` instead of the page popping itself, for an owner that keeps its own
            screen stack; most callers leave it out.
    """

    def __init__(
        self,
        markdown: str,
        *,
        title: str = "",
        on_cancel: Callable[[], None] | None = None,
    ) -> None:
        """Keep the document and start at its first line."""
        super().__init__()
        self.title = title.strip()
        self.on_cancel = on_cancel
        self.document = Markdown(markdown)
        self.offset = 0
        self._body_rows = 0

    @property
    def focusable(self) -> bool:
        """Take the keyboard when the page opens, so its keys work without a click."""
        return True

    def close(self) -> None:
        """Leave the page: through the owner's callback when it gave one, else by popping itself."""
        if self.on_cancel is not None:
            self.on_cancel()
        elif self.app is not None and self.app.screens.top.widget is self:
            self.app.pop_screen()
            self.app.request_layout()

    def capture_event(self, event, host) -> bool:
        """Close on Escape before anything else can take the key."""
        if isinstance(event, KeyEvent) and event.key == "escape":
            self.close()
            return True
        return False

    def handle(self, event, host) -> bool:
        """Scroll the document, or close it."""
        if isinstance(event, MouseEvent):
            if event.action is MouseAction.SCROLL_UP:
                self._scroll(-WHEEL_ROWS)
            elif event.action is MouseAction.SCROLL_DOWN:
                self._scroll(WHEEL_ROWS)
            else:
                return False
            host.invalidate()
            return True
        key = self._key_of(event)
        if key is None:
            return False
        if key in ("up", "k"):
            self._scroll(-1)
        elif key in ("down", "j"):
            self._scroll(1)
        elif key == "page_up":
            self._scroll(-max(1, self._body_rows - 1))
        elif key == "page_down":
            self._scroll(max(1, self._body_rows - 1))
        elif key == "home":
            self.offset = 0
        elif key == "end":
            self._scroll(10**9)
        elif key in ("q", "escape"):
            self.close()
        else:
            return False
        host.invalidate()
        return True

    @staticmethod
    def _key_of(event: object) -> str | None:
        """Return the key an event names, whether it came as a key or as typed text."""
        if isinstance(event, KeyEvent):
            return None if event.alt or event.control else event.key
        text = getattr(event, "text", None)
        return text if isinstance(text, str) and len(text) == 1 else None

    def _scroll(self, rows: int) -> None:
        """Move the document, never past its first line or its last."""
        total = self.document.line_count(self._width())
        furthest = max(0, total - self._body_rows)
        self.offset = min(max(0, self.offset + rows), furthest)

    def _width(self) -> int:
        """Return the columns the document is rendered in."""
        return max(1, self.rect.width - 4)

    def render(self, canvas) -> None:
        """Fill the page, then draw the title, the document, and the footer."""
        if self.rect.empty:
            return
        theme = self.theme
        rect = self.rect
        canvas.fill(rect.x, rect.y, rect.width, rect.height, Style(background=theme.surface_alt))
        room = self._width()
        self.document.theme = theme
        top = rect.y + 1
        if self.title:
            canvas.draw_text(
                rect.x + 2, rect.y + 1, self.title, Style(foreground=theme.text, bold=True), max_width=room
            )
            top = rect.y + 3
        self._body_rows = max(0, rect.bottom - 2 - top)
        lines = self.document.lines(room)
        self.offset = min(self.offset, max(0, len(lines) - self._body_rows))
        for row, line in enumerate(lines[self.offset : self.offset + self._body_rows]):
            canvas.draw_spans(rect.x + 2, top + row, line.spans, max_width=room)
        hint = SCROLL_HINT if len(lines) > self._body_rows else SHORT_HINT
        canvas.draw_text(
            rect.x + 2,
            rect.bottom - 1,
            hint,
            Style(foreground=theme.muted, background=theme.surface_alt),
            max_width=room,
        )


__all__ = ["DocumentPage"]
