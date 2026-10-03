"""Bottom-panel presentation for the shell's own pages."""

from __future__ import annotations

from ....tui import Anchor, Border, Overlay, OverlaySlot, Style, Widget


def bottom_panel(widget: Widget, *, rows: int, color: str | None = None) -> Widget:
    """Frame one widget and anchor it to the bottom of the screen.

    The caller owns the decision: a command handler that wants a panel wraps its
    page in this and hands the result to :class:`~zettcode.app.commands.CommandResult`,
    while one that wants the whole screen hands over the bare widget.

    Args:
        widget: Content of the panel; the frame insets it by one cell.
        rows: Height of the panel, counting its frame.
        color: Hex colour of the frame glyphs; ``None`` keeps the terminal's
            default foreground.
    """
    frame = Border(widget, style=Style(foreground=color))
    anchor = Anchor(horizontal="stretch", vertical="end", height=rows)
    return Overlay([OverlaySlot(frame, anchor)])
