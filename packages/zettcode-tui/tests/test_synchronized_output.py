"""Synchronized output: a frame reaches the screen whole, or not at all.

A quick drag redraws a sprite on most frames, and a terminal that refreshes while a frame is half parsed shows the old
place erased and the new one not yet painted. The renderer asks for the update to be held back (DEC private mode
2026); these tests replay its bytes on a small virtual terminal that honours the request, which is the only way to say
what a reader would have seen.
"""

from __future__ import annotations

import random
import re
from io import StringIO

from zettcode.tui import Canvas, DifferentialRenderer, Style
from zettcode.tui.render.renderer import BEGIN_SYNC, END_SYNC, HIDE_CURSOR, SHOW_CURSOR

CSI = re.compile(r"\x1b\[([?0-9;]*)([A-Za-z])")


class Screen:
    """A terminal that keeps a grid and, while a synchronized update is open, shows the grid as it was before it."""

    def __init__(self, width: int, height: int) -> None:
        self.width, self.height = width, height
        self.grid = [[" "] * width for _ in range(height)]
        self.shown = [row[:] for row in self.grid]
        self.synchronized = False
        self.cursor_visible = True
        self.shown_cursor_visible = True
        self.row = self.column = 0
        #: Whether any cell was written while the cursor showed, which on a terminal that cannot hold the update
        #: back is the cursor running across the screen.
        self.drew_with_cursor_visible = False
        #: Every state the reader could have seen: the screen at each moment the terminal chose to refresh.
        self.refreshes: list[tuple[list[list[str]], bool]] = []

    def refresh(self) -> None:
        self.shown = [row[:] for row in self.grid]
        self.shown_cursor_visible = self.cursor_visible
        self.refreshes.append((self.shown, self.shown_cursor_visible))

    def feed(self, data: str, *, refresh_every: int = 1) -> None:
        """Parse ``data`` the way a terminal does, refreshing every ``refresh_every`` characters it consumed.

        A terminal that supports synchronized output does not refresh inside the bracket however often it is asked
        to; one that does not refresh whenever it likes. The point of the tests is the first kind.
        """
        index = consumed = 0
        while index < len(data):
            match = CSI.match(data, index)
            if match:
                self.csi(match.group(1), match.group(2))
                index = match.end()
            else:
                self.put(data[index])
                index += 1
            consumed += 1
            if consumed % refresh_every == 0 and not self.synchronized:
                self.refresh()

    def csi(self, args: str, final: str) -> None:
        if args == "?2026":
            self.synchronized = final == "h"
            if not self.synchronized:
                self.refresh()
        elif args == "?25":
            self.cursor_visible = final == "h"
        elif final == "H":
            row, _, column = args.partition(";")
            self.row, self.column = int(row or 1) - 1, int(column or 1) - 1
        elif final == "J" and args == "2":
            self.grid = [[" "] * self.width for _ in range(self.height)]

    def put(self, character: str) -> None:
        if self.cursor_visible:
            self.drew_with_cursor_visible = True
        if 0 <= self.row < self.height and 0 <= self.column < self.width:
            self.grid[self.row][self.column] = character
        self.column += 1


def canvas_of(width: int, height: int, marks: dict[tuple[int, int], str]) -> Canvas:
    canvas = Canvas(width, height)
    for (x, y), character in marks.items():
        canvas.set_cell(x, y, character, Style(foreground="#ffffff"))
    return canvas


def letters(canvas: Canvas) -> list[list[str]]:
    return [[cell.character or " " for cell in row] for row in canvas.cells]


def sprite_at(x: int, y: int) -> dict[tuple[int, int], str]:
    return {(x + dx, y + dy): "#" for dx in range(6) for dy in range(3)}


def test_a_frame_that_paints_is_one_synchronized_update_with_the_cursor_hidden_inside_it():
    output = StringIO()
    renderer = DifferentialRenderer(output)

    renderer.render(canvas_of(20, 5, sprite_at(2, 1)), cursor=(3, 2))

    frame = output.getvalue()
    assert frame.startswith(BEGIN_SYNC + HIDE_CURSOR)
    assert frame.endswith("\x1b[3;4H" + SHOW_CURSOR + END_SYNC)
    assert frame.count(BEGIN_SYNC) == frame.count(END_SYNC) == 1


def test_a_frame_with_no_cursor_does_not_say_hide_twice():
    output = StringIO()
    DifferentialRenderer(output).render(canvas_of(20, 5, sprite_at(2, 1)), cursor=None)
    assert output.getvalue().count(HIDE_CURSOR) == 1


def test_a_frame_that_changes_nothing_and_leaves_the_cursor_where_it_was_writes_nothing():
    output = StringIO()
    renderer = DifferentialRenderer(output)
    canvas = canvas_of(20, 5, sprite_at(2, 1))
    renderer.render(canvas, cursor=(3, 2))
    first = output.getvalue()

    renderer.render(canvas_of(20, 5, sprite_at(2, 1)), cursor=(3, 2))
    assert output.getvalue() == first, "the same picture and cursor cost no bytes"

    renderer.render(canvas_of(20, 5, sprite_at(2, 1)), cursor=(4, 2))
    assert output.getvalue()[len(first) :] == "\x1b[3;5H" + SHOW_CURSOR, "a moved cursor is said without a bracket"

    renderer.render(canvas_of(20, 5, sprite_at(2, 1)), cursor=None)
    assert output.getvalue().endswith(HIDE_CURSOR)


def test_a_forgotten_frame_is_repainted_in_full_even_if_the_picture_is_the_same():
    output = StringIO()
    renderer = DifferentialRenderer(output)
    canvas = canvas_of(20, 5, sprite_at(2, 1))
    renderer.render(canvas, cursor=(3, 2))
    renderer.reset()
    before = len(output.getvalue())

    renderer.render(canvas, cursor=(3, 2))

    assert output.getvalue()[before:].startswith(BEGIN_SYNC + HIDE_CURSOR + "\x1b[2J")


def test_a_quick_drag_never_shows_the_old_place_erased_and_the_new_one_unpainted():
    """Move a sprite by random jumps, a terminal refreshing at every byte it can: each refresh is a whole frame."""
    width, height = 40, 12
    rng = random.Random(7)
    output = StringIO()
    renderer = DifferentialRenderer(output)
    screen = Screen(width, height)
    x, y = 30, 5
    shown_before = letters(Canvas(width, height))
    for _ in range(120):
        x = min(width - 6, max(0, x + rng.choice((-14, -5, -1, 0, 1, 5, 14))))
        y = min(height - 3, max(0, y + rng.choice((-4, -1, 0, 1, 4))))
        canvas = canvas_of(width, height, sprite_at(x, y))
        output.seek(0)
        output.truncate()
        renderer.render(canvas, cursor=None)
        before = len(screen.refreshes)

        screen.feed(output.getvalue(), refresh_every=1)

        seen = [grid for grid, _ in screen.refreshes[before:]]
        # Whatever the terminal showed while this frame was arriving is the picture before it or the picture it
        # drew, and the last thing shown is the finished frame: never a place erased with the next not yet painted.
        assert all(grid in (shown_before, letters(canvas)) for grid in seen)
        if output.getvalue():
            assert seen and seen[-1] == letters(canvas)
        shown_before = letters(canvas)


def test_the_cursor_is_never_shown_while_a_frame_is_being_written():
    output = StringIO()
    renderer = DifferentialRenderer(output)
    screen = Screen(30, 8)
    renderer.render(canvas_of(30, 8, sprite_at(1, 1)), cursor=(5, 5))
    screen.feed(output.getvalue(), refresh_every=1)
    output.seek(0)
    output.truncate()
    screen.drew_with_cursor_visible = False

    renderer.render(canvas_of(30, 8, sprite_at(9, 3)), cursor=(5, 5))
    screen.feed(output.getvalue(), refresh_every=1)

    assert screen.drew_with_cursor_visible is False
    assert screen.refreshes[-1][1] is True, "and it is back once the frame is done"
    assert (screen.row, screen.column) == (5, 5), "where a widget wanted it"
