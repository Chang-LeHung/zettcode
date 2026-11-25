"""The bottom panel ``/ssh`` opens: a target, how to sign in, and the two things to do with it.

The page keeps the shape the other plugin panels use — a title with the state at the right, rows with the mark on
the left and the value beside it, one line saying what the marked row does, and the keys — rather than boxes, so it
reads like ``/monitor`` and ``/pet``. A value that is typed is drawn where the others are, with a caret, and a
password is painted as bullets.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from time import monotonic

from zettcode.plugin_api import (
    SWITCH_WIDTH,
    Canvas,
    Host,
    MouseAction,
    MouseEvent,
    PasteEvent,
    Rail,
    Style,
    TextEvent,
    Widget,
    blend,
    display_width,
    draw_switch,
    pressed,
    truncate,
)

from .transport import Target

#: A blank, the title, a blank, the seven rows, a blank, what the marked row does, and the keys.
ROWS = 13

#: The first row of the list, counted from the top of the panel.
LIST_TOP = 3

#: Columns a row's name takes, and the width of the switch's longer word ("key/agent").
NAME_WIDTH = 12
WORD_WIDTH = 9

#: The fewest columns a value keeps before the note beside it is dropped instead of squeezing it.
MIN_VALUE = 12

MASK = "\u2022"
MARK = "\u25b8"
ON, OFF = "\u25c9", "\u25cb"

#: What the right-hand column of each row says, in the few words a row has room for. The sign-in rows say
#: something else once the switch is on password (:meth:`SSHPage._summary`).
SUMMARIES: tuple[str, ...] = (
    "select or type a host",
    "remote working directory",
    "from ~/.ssh/config",
    "no password needed",
    "not needed",
    "check, then use it",
    "close the remote channel",
)

#: The rows, in order: the label, and the sentence the line under the list shows while the mark is on it.
ROWS_INFO: tuple[tuple[str, str], ...] = (
    ("Host", "an alias from ~/.ssh/config, or user@hostname typed by hand"),
    ("Workspace", "the absolute remote directory every remote tool works in"),
    ("User", "leave empty to use the user ~/.ssh/config gives this host"),
    ("Sign in", "key/agent signs in with your SSH key and needs no password"),
    ("Password", "kept in memory for this session only; never saved or inherited"),
    ("Connect", "check the remote workspace, then use this target"),
    ("Disconnect", "close the channel; the local tools keep working either way"),
)

HOST, WORKSPACE, USER, SIGN_IN, PASSWORD, CONNECT, LOCAL = range(7)


class SSHPage(Widget):
    """Choose a remote workspace and how to sign in, then connect or go back to local tools.

    Shape::

        SSH                                                       ● connected · full

          ▸ Host        build-host-1         select or type a host
            Workspace   /srv/project         remote working directory
            User        (from config)        from ~/.ssh/config
            Sign in     ●───────── key/agent no password needed
            Password    (none needed)        not needed
            Connect     ↵ enter              check, then use it
            Disconnect  ↵ enter              close the remote channel

          Host: an alias from ~/.ssh/config, or user@hostname typed by hand
          ↑ ↓ row · ← → switch · F2 hosts · enter hosts/next · esc cancel

    The value column gives a long value the room the note on its right does not need, so a remote path is shown
    from its start. A note is left out when the panel is too narrow for it (``left < 18``), and on a panel shorter
    than the rows the list scrolls to keep the marked row on screen. Picking a host first replaces these rows with
    the aliases from ``~/.ssh/config`` and "Enter a host manually…", drawn the same way.
    Up, Down and Tab move the mark; Left, Right and Space set the sign-in method; printing and pasting edit the row
    the mark is on. Typing in the password row selects password sign-in by itself, and an empty password is refused
    before a connection is attempted. Enter on Connect (or Disconnect) does it; on Host with aliases it opens the
    host picker; elsewhere it moves down one row.
    Escape cancels, and cancelling while a connection is being checked keeps the previous target.
    """

    HINT = "\u2191 \u2193 row \u00b7 \u2190 \u2192 switch \u00b7 F2 hosts \u00b7 enter hosts/next \u00b7 esc cancel"
    HINT_ACTION = "\u2191 \u2193 row \u00b7 enter do it \u00b7 esc cancel"
    HINT_HOSTS = "\u2191 \u2193 host \u00b7 enter choose \u00b7 esc back"

    def __init__(
        self,
        *,
        target: Target | None,
        status: Callable[[], str],
        on_apply: Callable[[Target | None, str], Awaitable[None]],
        on_close: Callable[[], None],
        aliases: tuple[str, ...] = (),
    ) -> None:
        super().__init__()
        self.target = target
        if target is None:
            self.values = ["", "", ""]
        else:
            self.values = [target.host, target.path, target.user or ""]
        self.cursors = [len(value) for value in self.values]
        self.rail = Rail(("key/agent", "password"), 0 if target is None or target.auth == "key" else 1)
        self.password = ""
        self.mark = 0
        self.error = ""
        self.notice = ""
        self.closed = False
        self._started = monotonic()
        self._cancelling = False
        self.status = status
        self.on_apply = on_apply
        self.on_close = on_close
        self.pending: asyncio.Task[None] | None = None
        self.aliases = aliases
        self.choosing = bool(aliases) and target is None
        self.choice = 0
        self.scroll = 0
        self._token = f"ssh-panel:{id(self)}"

    # -- the switch and its slide ----------------------------------------------------------
    @property
    def auth(self) -> str:
        return "key" if self.rail.selected == 0 else "password"

    @auth.setter
    def auth(self, value: str) -> None:
        self.rail.choose(0 if value == "key" else 1, self._now(), instant=True)

    def _now(self) -> float:
        return self.app.clock() if self.app is not None else monotonic()

    def _choose(self, index: int) -> None:
        """Send the knob to key/agent (0) or password (1), sliding unless the reader asked for no motion."""
        reduced = self.app is not None and self.app.reduced_motion
        if self.rail.choose(index, self._now(), instant=reduced) and self.app is not None:
            self.app.scheduler.animate(self._token)

    def on_mount(self) -> None:
        """Keep a frame loop while the knob is moving or a connection is being checked."""
        self._animate(self.rail.moving or self._connecting())

    def on_unmount(self) -> None:
        """Cancel a probe still in flight and put the frame loop away.

        Ctrl-C on a page closes it without asking it (``Overlay`` has no interrupt), so this is the one hook that
        runs: a connection checked after the panel is gone must not take the tools over with no panel to say so.
        """
        self.closed = True
        if self._connecting() and self.pending is not None:
            self.pending.cancel()
        self.rail.moving = False
        self._animate(False)

    def _animate(self, active: bool) -> None:
        if self.app is not None and not self.app.reduced_motion:
            self.app.scheduler.animate(self._token, active=active)

    def on_tick(self) -> bool:
        """Arrive the knob and say whether anything is still moving; the dots advance with the clock."""
        landed = self.rail.arrive(self._now())
        if not self.rail.moving and not self._connecting():
            self._animate(False)
        return self.rail.moving or landed or self._connecting()

    def _connecting(self) -> bool:
        return self.pending is not None and not self.pending.done()

    def notice_now(self, now: float | None = None) -> str:
        """Return the working line: the word with one to three dots, from the clock rather than the frame count."""
        if not self.notice:
            return ""
        elapsed = (self._now() if now is None else now) - self._started
        return self.notice + "." * (1 + int(max(0.0, elapsed) / 0.4) % 3)

    # -- what the rows hold ---------------------------------------------------------------
    @property
    def focusable(self) -> bool:
        return True

    def field(self, row: int) -> int | None:
        """Return which typed value a row edits, if it edits one."""
        return {HOST: 0, WORKSPACE: 1, USER: 2, PASSWORD: 3}.get(row)

    def caret(self, row: int) -> int:
        return self.cursors[row] if row != PASSWORD else len(self.password)

    def value(self, row: int) -> str:
        if row == PASSWORD:
            return self.password
        index = self.field(row)
        return "" if index is None else self.values[index]

    def target_now(self) -> Target:
        """Return the target the rows describe, refusing a password sign-in with no password."""
        if self.auth == "password" and not self.password:
            raise ValueError("Enter the password for password sign-in, or switch to key/agent")
        host, path, user = (self.values + ["", "", ""])[:3]
        return Target(host, path, user or None, self.auth)

    # -- choosing a configured host -------------------------------------------------------
    def choose(self, index: int) -> None:
        """Take a host from the list, or go to the host row to type one."""
        if index < len(self.aliases):
            self.values[0] = self.aliases[index]
            self.cursors[0] = len(self.values[0])
            self.mark = WORKSPACE
        else:
            self.mark = HOST
        self.choosing = False
        self.error = ""

    def _hosts(self) -> None:
        if self.aliases:
            self.choosing = True
            self.choice = min(self.choice, len(self.aliases))

    # -- doing it -------------------------------------------------------------------------
    def confirm(self, host: Host) -> None:
        if self.pending is not None and not self.pending.done():
            return
        try:
            target = None if self.mark == LOCAL else self.target_now()
        except ValueError as error:
            self.error = str(error)
            return

        async def apply() -> None:
            self.error = ""
            self._cancelling = False
            self.notice = "Disconnecting" if target is None else "Connecting"
            self._started = self._now()
            self._animate(True)
            host.invalidate()
            try:
                await self.on_apply(target, "" if target is None else self.password)
            except asyncio.CancelledError:
                if not self.closed:
                    self.error = "Cancelled; the previous target is unchanged"
            except Exception as error:
                if not self.closed:
                    self.error = str(error)
            else:
                if not self.closed:
                    self.on_close()
            finally:
                self.notice = ""
                host.invalidate()

        self.pending = asyncio.create_task(apply())

    # -- editing --------------------------------------------------------------------------
    def insert(self, text: str) -> None:
        index = self.field(self.mark)
        if index is None:
            return
        # A host copied out of a terminal arrives with the line's newline; take the line, refuse anything else.
        if text.endswith("\n"):
            text = text[:-1].rstrip("\r")
        if any(ord(char) < 32 or ord(char) == 127 for char in text):
            self.error = "This row takes single-line text"
            return
        if not text:
            return
        if index == 3:
            if self.auth != "password":
                self.auth = "password"
            value = self.password
            if len(value) + len(text) > 1024:
                self.error = "Password exceeds 1024 characters"
                return
            cursor = len(value)
            self.password = value[:cursor] + text
        else:
            cursor = self.cursors[index]
            value = self.values[index]
            if len(value) + len(text) > 4096:
                self.error = "This row exceeds 4096 characters"
                return
            self.values[index] = value[:cursor] + text + value[cursor:]
            self.cursors[index] = cursor + len(text)
        self.error = ""

    def _edit_key(self, key: str) -> bool:
        index = self.field(self.mark)
        if index is None:
            return False
        value = self.password if index == 3 else self.values[index]
        cursor = len(value) if index == 3 else self.cursors[index]
        if key == "left":
            cursor = max(0, cursor - 1)
        elif key == "right":
            cursor = min(len(value), cursor + 1)
        elif key == "home":
            cursor = 0
        elif key == "end":
            cursor = len(value)
        elif key == "backspace" and cursor:
            value, cursor = value[: cursor - 1] + value[cursor:], cursor - 1
        elif key == "delete":
            value = value[:cursor] + value[cursor + 1 :]
        else:
            return False
        if index == 3:
            self.password = value
        else:
            self.values[index], self.cursors[index] = value, cursor
        self.error = ""
        return True

    def capture_event(self, event: object, host: Host) -> bool:
        if pressed(event) == "escape":
            if self._connecting():
                # Cancel once: a second Escape must not abort the close that frees the password.
                if not self._cancelling and self.pending is not None:
                    self._cancelling = True
                    self.notice = "Cancelling"
                    self.pending.cancel()
            elif self.choosing:
                self.choosing = False
            else:
                self.on_close()
            return True
        return False

    def handle(self, event: object, host: Host) -> bool:
        if self.pending is not None and not self.pending.done():
            return True
        if self.choosing:
            return self._handle_hosts(event, host)
        if isinstance(event, MouseEvent):
            return self._handle_mouse(event, host)
        if isinstance(event, (TextEvent, PasteEvent)):
            if isinstance(event, TextEvent) and (event.control or event.alt):
                return False
            # A space on the sign-in row is the switch's key, not text for a field that is not editable.
            if self.mark == SIGN_IN and event.text == " ":
                self._choose(1 - self.rail.selected)
                self.error = ""
                return True
            self.insert(event.text)
            return True
        key = pressed(event)
        if key is None:
            return False
        if key == "f2":
            self._hosts()
            return True
        if key in {"tab", "down", "backtab", "up"}:
            step = -1 if key in {"up", "backtab"} else 1
            self.mark = (self.mark + step) % len(ROWS_INFO)
            self.error = ""
            return True
        if key == "enter":
            if self.mark == HOST and self.aliases:
                self._hosts()
            elif self.mark in (CONNECT, LOCAL):
                self.confirm(host)
            else:
                self.mark = (self.mark + 1) % len(ROWS_INFO)
            return True
        if self.mark == SIGN_IN and key in {"left", "right", "space"}:
            if key == "left":
                self._choose(0)
            elif key == "right":
                self._choose(1)
            else:
                self._choose(1 - self.rail.selected)
            self.error = ""
            return True
        return self._edit_key(key)

    def _handle_hosts(self, event: object, host: Host) -> bool:
        count = len(self.aliases) + 1
        visible = self._visible()
        if isinstance(event, MouseEvent):
            row = event.y - self.rect.y - LIST_TOP
            if event.action is MouseAction.DOWN and visible > 0 and 0 <= row < visible and self.scroll + row < count:
                self.choose(self.scroll + row)
                return True
            return False
        key = pressed(event)
        if key in {"up", "down", "tab", "backtab"}:
            self.choice = (self.choice + (-1 if key in {"up", "backtab"} else 1)) % count
            self.scroll = max(0, min(self.scroll, self.choice))
            if self.choice >= self.scroll + visible:
                self.scroll = self.choice - visible + 1
        elif key == "enter":
            self.choose(self.choice)
        else:
            return False
        return True

    def _handle_mouse(self, event: MouseEvent, host: Host) -> bool:
        if event.action is not MouseAction.DOWN:
            return False
        top, visible = self._top(), self._visible()
        row = event.y - (self.rect.y + LIST_TOP) + top
        if visible <= 0 or not top <= row < top + visible:
            return False
        was = self.mark
        self.mark, self.error = row, ""
        switch_end = self._switch_column() + SWITCH_WIDTH + 1
        if row == SIGN_IN and self._switch_column() <= event.x <= switch_end:
            self._choose(1 - self.rail.selected)
        elif row in (CONNECT, LOCAL) and was == row:
            self.confirm(host)
        elif row == HOST and was == row:
            self._hosts()
        return True

    # -- painting -------------------------------------------------------------------------
    def _switch_column(self) -> int:
        return self.rect.x + 2 + 2 + NAME_WIDTH

    def _state(self) -> tuple[str, str]:
        """Return the word at the title's right and the colour role it wears."""
        if self._connecting():
            return self.notice_now() or "Working", "accent"
        if self.target is None:
            return "off", "muted"
        return self.status(), "accent"

    def render(self, canvas: Canvas) -> None:
        if self.rect.empty:
            return
        theme = self.theme
        surface = theme.surface_alt
        canvas.fill(self.rect.x, self.rect.y, self.rect.width, self.rect.height, Style(background=surface))
        x = self.rect.x + 2
        room = max(0, self.rect.width - 4)
        muted = Style(foreground=theme.muted, background=surface)
        bold = Style(foreground=theme.text, background=surface, bold=True)
        quiet = blend(theme.muted, surface, 0.25)
        quiet_style = Style(foreground=quiet, background=surface)
        accent = Style(foreground=theme.accent, background=surface, bold=True)
        canvas.draw_text(x, self.rect.y + 1, "SSH", bold, max_width=room)
        state, role = self._state()
        style = accent if role == "accent" else muted
        canvas.draw_text(self.rect.right - 2 - display_width(state), self.rect.y + 1, state, style, max_width=room)
        if self.choosing:
            self._render_hosts(canvas, x, room, muted, bold, accent, surface)
            return
        groove = blend(theme.muted, surface, 0.55)
        column = self._switch_column()
        top = self._top()
        visible = self._visible()
        for row in range(top, min(len(ROWS_INFO), top + visible)):
            y = self.rect.y + LIST_TOP + row - top
            marked = row == self.mark
            if marked:
                canvas.draw_text(x, y, MARK, Style(foreground=theme.accent, background=surface, bold=True))
            canvas.draw_text(
                x + 2,
                y,
                ROWS_INFO[row][0],
                bold if marked else Style(foreground=theme.text, background=surface),
                max_width=NAME_WIDTH,
            )
            note = self._summary(row)
            note_x = self._render_value(canvas, row, y, column, surface, groove, muted, quiet_style, accent, note)
            left = self.rect.right - 2 - note_x
            if note_x and left >= 18:
                canvas.draw_text(
                    note_x,
                    y,
                    truncate(note, left),
                    Style(foreground=blend(theme.muted, surface, 0.15), background=surface),
                    max_width=left,
                )
        error = self.error
        if error:
            line, style = error, Style(foreground=theme.error, background=surface)
        elif self.notice:
            line = self.notice_now()
            style = accent
        else:
            line = f"{ROWS_INFO[self.mark][0]}: {ROWS_INFO[self.mark][1]}"
            style = muted
        canvas.draw_text(x, self.rect.bottom - 2, truncate(line, room), style, max_width=room)
        hint = self.HINT_ACTION if self.mark in (CONNECT, LOCAL) else self.HINT
        canvas.draw_text(x, self.rect.bottom - 1, truncate(hint, room), muted, max_width=room)

    def _visible(self) -> int:
        """Return how many rows fit between the title and the two lines under the list; none on a tiny panel."""
        return max(0, self.rect.height - LIST_TOP - 2)

    def _top(self) -> int:
        """Return the first row drawn, so the marked row stays on screen on a short terminal."""
        visible = self._visible()
        if self.mark < visible:
            return 0
        return min(self.mark - visible + 1, max(0, len(ROWS_INFO) - visible))

    def _summary(self, row: int) -> str:
        """Return the words at the row's right, which follow the switch where they must."""
        if row == USER and self.values[2]:
            return "explicit account"
        if row == SIGN_IN:
            return "no password needed" if self.auth == "key" else "asks for a password"
        if row == PASSWORD:
            return "not needed" if self.auth == "key" else "this session only"
        return SUMMARIES[row]

    def _layout(self, column: int, shown: str, note: str) -> tuple[int, int]:
        """Return the value's width and where its note may start (0 when there is no room for a note).

        The value always gets its room first: a note takes the space left when the value is short, starts one cell
        after a value that grows into it, and is dropped rather than squeezing the value below ``MIN_VALUE``.
        """
        right = self.rect.right - 2
        available = right - column
        if available <= 0:
            return 0, 0
        aligned = column + SWITCH_WIDTH + 1 + WORD_WIDTH + 1
        wanted = max(aligned, column + min(display_width(shown), available) + 1)
        note_x = min(wanted, right - 18)
        if note_x - 1 - column < MIN_VALUE or right - note_x < 18 or display_width(note) < 1:
            return available, 0
        return note_x - 1 - column, note_x

    def _render_value(
        self,
        canvas: Canvas,
        row: int,
        y: int,
        column: int,
        surface: object,
        groove: object,
        muted: Style,
        quiet: Style,
        accent: Style,
        note: str,
    ) -> int:
        theme = self.theme
        if row == SIGN_IN:
            word = self.rail.words[self.rail.selected]
            start = column + SWITCH_WIDTH + 1
            shown = f"{' ' * SWITCH_WIDTH} {word}"
            width, note_x = self._layout(column, shown, note)
            # The switch's word does not shrink: if the note would cut it, the note goes instead.
            if note_x and note_x - 1 - start < display_width(word):
                width, note_x = self.rect.right - 2 - column, 0
            # Index 0 (key/agent) is the knob at the left and index 1 (password) at the right, so Right moves it right.
            draw_switch(
                canvas,
                theme,
                y,
                column,
                self.rail.position(self._now()),
                groove,  # type: ignore[arg-type]
            )
            style = Style(
                foreground=theme.accent if self.rail.selected == 0 else theme.warning,
                background=surface,  # type: ignore[arg-type]
                bold=self.mark == row,
            )
            room_for_word = max(0, min(width, max(0, self.rect.right - 2 - start)))
            canvas.draw_text(start, y, word, style, max_width=room_for_word)
            return note_x
        if row in (CONNECT, LOCAL):
            width, note_x = self._layout(column, "\u21b5 enter", note)
            canvas.draw_text(
                column,
                y,
                "\u21b5 enter",
                accent if self.mark == row else quiet,
                max_width=width,
            )
            return note_x
        index = self.field(row)
        value = self.value(row)
        cursor = self.caret(row)
        if row == PASSWORD:
            # In key/agent mode the row holds nothing to edit: no dash to put a caret on.
            shown = MASK * len(value) if self.auth == "password" else ""
            placeholder = "(required)" if self.auth == "password" else "(none needed)"
        else:
            assert index is not None
            value = self.values[index]
            cursor = self.cursors[index]
            placeholder = ("(type a host)", "(remote path)", "(from config)")[index]
            shown = value
        # A focused row asks for one cell past its value so the caret can sit after the last character instead of
        # painting over it; an unmarked row asks for none.
        reserve = " " if self.mark == row and row != PASSWORD and shown else ""
        width, note_x = self._layout(column, (shown or placeholder) + reserve, note)
        editing = self.mark == row and self.field(row) is not None
        if editing and width:
            # The row being edited is a field: a raised band of its own, marked at its left edge like a composer's
            # prompt, so it is visible that typing goes here.
            canvas.fill(column - 1, y, width + 1, 1, Style(background=theme.surface))
            canvas.draw_text(column - 1, y, "\u258f", Style(foreground=theme.accent, background=theme.surface))
        field_background = theme.surface if editing else surface
        if not shown:
            canvas.draw_text(
                column,
                y,
                truncate(placeholder, width),
                Style(foreground=theme.muted, background=field_background),  # type: ignore[arg-type]
                max_width=width,
            )
            start = 0
        else:
            # The caret wants a cell of its own: a value that exactly fills the room scrolls by one so its last
            # character stays visible. Only the edited row scrolls; the others show the value from its first
            # character, so a remote path is identified by the part that names it.
            scrolls = self.mark == row and row != PASSWORD and display_width(shown) + 1 > width
            start = max(0, cursor - width + 1) if scrolls else 0
            body = shown[start:] if row != PASSWORD else shown
            canvas.draw_text(
                column,
                y,
                truncate(body, width),
                Style(foreground=theme.text, background=field_background),  # type: ignore[arg-type]
                max_width=width,
            )
        if self.mark == row and shown:
            at = min(max(0, width - 1), display_width(shown[start:cursor]))
            char = (MASK if row == PASSWORD else shown[cursor : cursor + 1]) or " "
            # The block is painted first and the character on it, because a two-cell glyph (a Chinese character)
            # does not fit in the one-cell draw the caret used to be and disappeared behind the field's band.
            cells = max(1, display_width(char))
            canvas.fill(column + at, y, cells, 1, Style(background=theme.accent))
            canvas.draw_text(
                column + at,
                y,
                char,
                Style(foreground=field_background, background=theme.accent),  # type: ignore[arg-type]
                max_width=cells,
            )
        return note_x

    def _render_hosts(
        self,
        canvas: Canvas,
        x: int,
        room: int,
        muted: Style,
        bold: Style,
        accent: Style,
        surface: object,
    ) -> None:
        choices = (*self.aliases, "Enter a host manually\u2026")
        canvas.draw_text(
            x, self.rect.y + 2, f"{len(self.aliases)} configured host(s) in ~/.ssh/config", muted, max_width=room
        )
        visible = self._visible()
        for row, index in enumerate(range(self.scroll, min(len(choices), self.scroll + visible))):
            y = self.rect.y + LIST_TOP + row
            selected = index == self.choice
            if selected:
                canvas.draw_text(x, y, MARK, accent)
            canvas.draw_text(
                x + 2, y, truncate(choices[index], room - 2), bold if selected else muted, max_width=room - 2
            )
        canvas.draw_text(x, self.rect.bottom - 2, "Host: the host to connect to", muted, max_width=room)
        canvas.draw_text(x, self.rect.bottom - 1, self.HINT_HOSTS, muted, max_width=room)
