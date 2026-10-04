"""Bottom-panel presentation for the shell's own pages."""

from __future__ import annotations

from ....tui import Anchor, Overlay, OverlaySlot, Widget


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
