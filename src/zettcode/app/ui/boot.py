"""The first frame: the composer, in the rows the shell will fill in.

The application's own modules cost about 130 ms to import and build — a config
read, the runtime preview, the plugins, the widget library — and none of it is
needed to put an input box on screen. This module draws that box from the
framework alone, so the reader's first keystrokes have somewhere to land, and
the application replaces the tree as soon as it is built
(:meth:`~zettcode.tui.TuiApp.set_root`).

The rows are the shell's own, in its order and its sizes, and the ones this
frame has nothing to say yet are left blank rather than filled with a guess:
``VBox`` reserves them either way, so the swap fills them in without moving a
single row. The composer is the framework's :class:`~zettcode.tui.TextArea`,
which the real composer extends, configured the way the shell configures it —
so the box that is already on screen is the box that stays there.
"""

from __future__ import annotations

from pathlib import Path

from ...tui import PROMPT, Canvas, Constraints, Rule, Size, StatusBar, Text, TextArea, TextLine, VBox, Widget
from ...tui.layout import Slot
from ..agent.blocks import CONTENT_INDENT, WelcomeProcessor
from ..agent.entries import TextEntry
from . import labels
from .widgets.welcome import WELCOME

#: What the composer shows before anything is typed, matching the real one.
PLACEHOLDER = "Ask ZettCode to do anything"

#: Rows the real composer grows to before it scrolls, matching the shell's.
COMPOSER_ROWS = 8

#: The status word and session name the shell shows before anything runs. The
#: shell's own text, so the row it draws does not change when it arrives; the
#: test that compares the two frames cell by cell is what keeps them together.
IDLE_STATUS = "ready"
UNTITLED = "New session"


def boot_tree(workspace: Path, *, resuming: bool = False) -> VBox:
    """Return the frame drawn while the application is still loading.

    From the top: the header, its rule, the transcript, the blank row the shell
    keeps above the composer, the composer, and the status line. The header
    knows the workspace from the command line and the composer needs nothing
    else, so those two rows are the shell's own text; the transcript, the model
    name, and the token counters arrive with the application.

    Args:
        workspace: Directory the session runs in, as the header will show it.
        resuming: A stored session is about to be loaded, so the transcript will
            hold a conversation rather than a banner; drawing the banner would
            only be taken away again a moment later.
    """
    composer = TextArea(
        prompt=f"{PROMPT} ",
        placeholder=PLACEHOLDER,
        max_height=COMPOSER_ROWS,
        surface=True,
    )
    return VBox(
        [
            Slot(StatusBar(labels.header_left(workspace), ""), size=1),
            Slot(Rule(), size=1),
            Slot(Text("") if resuming else Welcome(), flex=1),
            Slot(Text(""), size=1),
            Slot(composer, size=lambda width: composer.preferred_height(width)),
            Slot(StatusBar(labels.status_left(IDLE_STATUS, UNTITLED), labels.status_right()), size=1),
        ]
    )


class Welcome(Widget):
    """The boot banner, drawn by the processor the transcript will use.

    The mark, its colours, the title's weight, and the hint's colour are the
    transcript's decisions, so they are asked for here rather than rebuilt: a
    second rendering would differ in some cell and that difference is what the
    reader sees as the banner flashing when the application replaces this tree.
    """

    def _lines(self, width: int) -> list[TextLine]:
        """Return the rows the banner paints at this width."""
        entry = TextEntry(id=0, kind="welcome", text=WELCOME)
        return WelcomeProcessor().lines(entry, max(1, width - CONTENT_INDENT), self.theme, 0)

    def measure(self, constraints: Constraints) -> Size:
        """Ask for the rows the banner needs at the width it was offered."""
        width = constraints.max_width if constraints.max_width is not None else 1
        lines = self._lines(max(1, width))
        return constraints.constrain(Size(max((line.width for line in lines), default=0), len(lines)))

    def render(self, canvas: Canvas) -> None:
        """Paint the banner's rows into the assigned rectangle."""
        if self.rect.empty:
            return
        width = max(1, self.rect.width - CONTENT_INDENT)
        for offset, line in enumerate(self._lines(self.rect.width)[: self.rect.height]):
            canvas.draw_spans(self.rect.x + CONTENT_INDENT, self.rect.y + offset, line.spans, max_width=width)
