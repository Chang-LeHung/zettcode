"""Bottom-panel presentation for the shell's own pages."""

from __future__ import annotations

from ....tui import Anchor, KeyEvent, Overlay, OverlaySlot, TextEvent, Widget


def bottom_panel(widget: Widget, *, rows: int) -> Widget:
    """Anchor one widget to the bottom of the screen as a panel.

    The caller owns the decision: a command handler that wants a panel wraps its
    page in this and hands the result to :class:`~zettcode.app.commands.CommandResult`,
    while one that wants the whole screen hands over the bare widget.

    The panel is not framed: a page fills its own rectangle with the raised
    surface, which is what separates it from the conversation above without a
    border eating two rows of content on every side.

    Args:
        widget: Content of the panel.
        rows: Height of the panel in cells.
    """
    anchor = Anchor(horizontal="stretch", vertical="end", height=rows)
    return Overlay([OverlaySlot(widget, anchor)])


def pressed(event: object) -> str | None:
    """Return the key one press names, whether the terminal sent it as a key or as text.

    A terminal has no "y" key: it sends the character, and the decoder reports a printable
    character as text, while arrows, Enter and Escape are named keys. A page that lists
    ``(y)`` beside a row has to answer both, or the shortcut it advertises only works for the
    tests that send a key event. Alt and Ctrl chords are not shortcuts and are left alone.
    """
    if isinstance(event, KeyEvent):
        return None if event.alt or event.control else event.key
    if isinstance(event, TextEvent) and len(event.text) == 1 and not (event.alt or event.control):
        return event.text
    return None
