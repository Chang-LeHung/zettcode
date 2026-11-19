"""The rounded search field the panels that narrow a list as the reader types are drawn with.

``/resume`` and ``/plugins`` both put a box above their rows and let typing fill it, so the box is drawn once, here:
its border takes the accent while it has the keyboard, its top rule carries the label, and the query sits inside with
a solid caret after it. While the field is empty it says what a query is matched against instead.
"""

from __future__ import annotations

from zettcode.tui import Canvas, Theme
from zettcode.tui.render import Style, display_width, truncate

#: The corners and rules of the search box, the rounded shape a form's fields are drawn in.
BOX_TOP_LEFT, BOX_TOP_RIGHT = "\u256d", "\u256e"
BOX_BOTTOM_LEFT, BOX_BOTTOM_RIGHT = "\u2570", "\u256f"
BOX_HORIZONTAL, BOX_VERTICAL = "\u2500", "\u2502"

#: The label on the box's top border, and the three rows the box spends: that border, the query, its foot.
SEARCH_LABEL = "Search"
BOX_ROWS = 3

#: Where typing lands in the box: "\u2588", a full block — the solid cursor vim leaves on the cell at the end of
#: a line, rather than a thin bar that is easy to miss in a terminal.
CARET = "\u2588"


def draw_search(
    canvas: Canvas,
    theme: Theme,
    x: int,
    y: int,
    room: int,
    query: str,
    *,
    hint: str,
    active: bool,
) -> None:
    """Draw the box at ``(x, y)`` over ``room`` columns, with its label, the query, and a caret while it has the keys.

    Args:
        canvas: What to paint on.
        theme: The colours the page is drawn in.
        x: Left column of the box.
        y: Its top row; the box spends :data:`BOX_ROWS` rows below this one.
        room: Columns it may take.
        query: What the reader has typed; empty draws ``hint`` in its place.
        hint: What the empty box says a query finds.
        active: Whether the box has the keyboard, which brightens its border and puts the caret in it.
    """
    if room < 2:
        return  # narrower than its own two uprights: there is no box to draw
    frame = Style(foreground=theme.accent_bright if active else theme.subtle, background=theme.surface_alt)
    rule = BOX_HORIZONTAL * max(0, room - 2)
    canvas.draw_text(x, y, f"{BOX_TOP_LEFT}{rule}{BOX_TOP_RIGHT}", frame, max_width=room)
    canvas.draw_text(x, y + 1, BOX_VERTICAL, frame)
    canvas.draw_text(x + room - 1, y + 1, BOX_VERTICAL, frame)
    canvas.draw_text(x, y + 2, f"{BOX_BOTTOM_LEFT}{rule}{BOX_BOTTOM_RIGHT}", frame, max_width=room)
    if room > 8:
        label = Style(
            foreground=theme.accent_bright if active else theme.muted,
            background=theme.surface_alt,
            bold=active,
        )
        canvas.draw_text(x + 2, y, f" {SEARCH_LABEL} ", label, max_width=room - 4)
    # A cell of padding inside each upright, then the query itself: no prompt mark, the box already says what
    # typing goes into.
    field_x = x + 2
    field_room = max(0, room - 4)
    if field_room <= 0:
        return  # a box too narrow to hold a query keeps its border and says nothing inside it
    muted = Style(foreground=theme.muted, background=theme.surface_alt)
    caret = Style(foreground=theme.text, background=theme.surface_alt)
    if query:
        shown = truncate(query, max(0, field_room - (1 if active else 0)))
        canvas.draw_text(
            field_x,
            y + 1,
            shown,
            Style(foreground=theme.text, background=theme.surface_alt),
            max_width=field_room,
        )
        if active:
            canvas.draw_text(field_x + display_width(shown), y + 1, CARET, caret, max_width=1)
    elif active:
        canvas.draw_text(field_x, y + 1, CARET + " ", caret, max_width=field_room)
        said = truncate(hint, max(0, field_room - 2))
        canvas.draw_text(field_x + 2, y + 1, said, muted, max_width=max(0, field_room - 2))
    else:
        canvas.draw_text(field_x, y + 1, truncate(hint, field_room), muted, max_width=field_room)
