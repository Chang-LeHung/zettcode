"""Terminal-only SSH target editor. Draft changes never reach the backend until confirmed."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from zettcode.plugin_api import (
    Canvas,
    Host,
    MouseAction,
    MouseEvent,
    PasteEvent,
    Style,
    TextEvent,
    Widget,
    display_width,
    pressed,
)

from .transport import Target

ROWS = 19


class SSHPage(Widget):
    """Edit host/path, apply the remote target, or explicitly return to local tools."""

    def __init__(
        self,
        *,
        target: Target | None,
        status: Callable[[], str],
        on_apply: Callable[[Target | None], Awaitable[None]],
        on_close: Callable[[], None],
        aliases: tuple[str, ...] = (),
    ) -> None:
        super().__init__()
        self.values = [target.host if target else "", target.path if target else ""]
        self.cursors = [len(value) for value in self.values]
        self.mark = 0
        self.error = ""
        self.status = status
        self.on_apply = on_apply
        self.on_close = on_close
        self.pending: asyncio.Task[None] | None = None
        self.aliases = aliases
        self.choosing = bool(aliases) and target is None
        self.choice = 0
        self.scroll = 0

    def choose(self, index: int) -> None:
        if index < len(self.aliases):
            self.values[0] = self.aliases[index]
            self.cursors[0] = len(self.values[0])
            self.mark = 1
        else:
            self.mark = 0
        self.choosing = False
        self.error = ""

    @property
    def focusable(self) -> bool:
        return True

    def capture_event(self, event: object, host: Host) -> bool:
        if pressed(event) == "escape":
            if self.pending is not None and not self.pending.done():
                self.pending.cancel()
            else:
                self.on_close()
            return True
        return False

    def confirm(self, host: Host) -> None:
        if self.pending is not None and not self.pending.done():
            return
        try:
            target = None if self.mark == 3 else Target(*self.values)
        except ValueError as error:
            self.error = str(error)
            return

        async def apply() -> None:
            self.error = "Connecting…" if target is not None else "Disconnecting…"
            host.invalidate()
            try:
                await self.on_apply(target)
            except asyncio.CancelledError:
                self.error = "Cancelled; the previous target is unchanged"
            except Exception as error:
                self.error = str(error)
            else:
                self.on_close()
            finally:
                host.invalidate()

        self.pending = asyncio.create_task(apply())

    def insert(self, text: str) -> None:
        if self.mark > 1:
            return
        if any(ord(char) < 32 or ord(char) == 127 for char in text):
            self.error = "Host and workspace must be single-line text"
            return
        cursor = self.cursors[self.mark]
        value = self.values[self.mark]
        if len(value) + len(text) > 4096:
            self.error = "Field exceeds 4096 characters"
            return
        self.values[self.mark] = value[:cursor] + text + value[cursor:]
        self.cursors[self.mark] += len(text)
        self.error = ""

    def handle(self, event: object, host: Host) -> bool:
        if self.pending is not None and not self.pending.done():
            return True
        if self.choosing:
            key = pressed(event)
            count = len(self.aliases) + 1
            if isinstance(event, MouseEvent):
                row = event.y - self.rect.y - 4
                if event.action is MouseAction.DOWN and 0 <= row < 8 and self.scroll + row < count:
                    self.choose(self.scroll + row)
                    return True
                return False
            if key in {"up", "down", "tab", "backtab"}:
                self.choice = (self.choice + (-1 if key in {"up", "backtab"} else 1)) % count
                self.scroll = max(0, min(self.scroll, self.choice))
                if self.choice >= self.scroll + 8:
                    self.scroll = self.choice - 7
            elif key == "enter":
                self.choose(self.choice)
            else:
                return False
            return True
        if isinstance(event, MouseEvent):
            row = event.y - self.rect.y
            if event.action is not MouseAction.DOWN:
                return False
            if row == 2 and self.aliases:
                self.choosing = True
            elif row in {5, 9}:
                self.mark = 0 if row == 5 else 1
            elif row in {12, 13}:
                self.mark = 2 if row == 12 else 3
                self.confirm(host)
            else:
                return False
            return True
        if isinstance(event, (TextEvent, PasteEvent)):
            if isinstance(event, TextEvent) and (event.control or event.alt):
                return False
            self.insert(event.text)
            return True
        key = pressed(event)
        if key == "f2" and self.aliases:
            self.choosing = True
        elif key in {"tab", "down", "backtab", "up"}:
            self.mark = (self.mark + (-1 if key in {"up", "backtab"} else 1)) % 4
            self.error = ""
        elif key == "enter":
            if self.mark < 2:
                self.mark += 1
            else:
                self.confirm(host)
        elif key in {"left", "right", "home", "end", "backspace", "delete"} and self.mark < 2:
            cursor = self.cursors[self.mark]
            value = self.values[self.mark]
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
            self.values[self.mark], self.cursors[self.mark] = value, cursor
        else:
            return False
        return True

    def render(self, canvas: Canvas) -> None:
        if self.rect.empty:
            return
        theme = self.theme
        background = theme.surface_alt
        canvas.fill(self.rect.x, self.rect.y, self.rect.width, self.rect.height, Style(background=background))
        x, y, width = self.rect.x + 2, self.rect.y, max(0, self.rect.width - 4)
        normal = Style(foreground=theme.text, background=background)
        muted = Style(foreground=theme.muted, background=background)
        canvas.draw_text(
            x, y + 1, "SSH workspace", Style(foreground=theme.text, background=background, bold=True), max_width=width
        )
        accent = Style(foreground=theme.accent, background=background, bold=True)
        if self.choosing:
            canvas.draw_text(x, y + 2, "Choose a host from ~/.ssh/config", muted, max_width=width)
            choices = (*self.aliases, "Enter a host manually…")
            for row, index in enumerate(range(self.scroll, min(len(choices), self.scroll + 8))):
                selected = index == self.choice
                canvas.draw_text(
                    x,
                    y + 4 + row,
                    ("▸ " if selected else "  ") + choices[index],
                    accent if selected else normal,
                    max_width=width,
                )
            canvas.draw_text(x, y + 15, "↑↓ choose · enter select · esc cancel", muted, max_width=width)
            return
        canvas.draw_text(
            x,
            y + 2,
            "F2: choose a configured host" if self.aliases else "No configured aliases — enter a host below",
            muted,
            max_width=width,
        )
        for index, (label, placeholder, top) in enumerate(
            (
                ("Host — type or paste", "alias or user@hostname", 4),
                ("Remote workspace — type or paste", "/absolute/remote/path", 8),
            )
        ):
            selected = self.mark == index
            style = accent if selected else muted
            canvas.draw_text(x, y + top - 1, label, style, max_width=width)
            inner = max(0, width - 2)
            canvas.draw_text(x, y + top, "┌" + "─" * inner + "┐", style, max_width=width)
            canvas.draw_text(x, y + top + 1, "│" + " " * inner + "│", style, max_width=width)
            canvas.draw_text(x, y + top + 2, "└" + "─" * inner + "┘", style, max_width=width)
            value = self.values[index]
            cursor = self.cursors[index]
            # Keep the caret visible while editing a long path. Width is measured in terminal cells.
            start = cursor
            while start and display_width(value[start - 1 : cursor]) < max(1, inner - 1):
                start -= 1
            shown = value[start:] if value else placeholder
            canvas.draw_text(x + 1, y + top + 1, shown, normal if value else muted, max_width=inner)
            if selected and not (self.pending is not None and not self.pending.done()) and inner:
                at = min(inner - 1, display_width(value[start:cursor]))
                char = value[cursor : cursor + 1] or (placeholder[0] if not value else " ")
                canvas.draw_text(
                    x + 1 + at,
                    y + top + 1,
                    char,
                    Style(foreground=background, background=theme.accent),
                    max_width=1,
                )
        for index, text in enumerate(("[ Connect / apply remote target ]", "[ Use local tools / disconnect ]"), 2):
            canvas.draw_text(
                x,
                y + 10 + index,
                ("▸ " if self.mark == index else "  ") + text,
                accent if self.mark == index else normal,
                max_width=width,
            )
        canvas.draw_text(
            x,
            y + 15,
            self.error or self.status(),
            Style(foreground=theme.error, background=background) if self.error else muted,
            max_width=width,
        )
        canvas.draw_text(
            x, y + 16, "Full permission required. Connect checks the remote workspace.", muted, max_width=width
        )
        canvas.draw_text(
            x, y + 17, "tab/↑↓ select · type/paste fields · enter connect · esc cancel", muted, max_width=width
        )
