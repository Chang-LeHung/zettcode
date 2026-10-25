"""The panel ``/monitor`` opens: the recording and image switches and the export action, in the style of ``/statusline``."""

from __future__ import annotations

from collections.abc import Callable

from zettcode.app.ui.widgets.panel import pressed
from zettcode.app.ui.widgets.statusline_page import SWITCH_WIDTH, draw_switch
from zettcode.tui import Canvas, Host, MouseAction, MouseEvent, Widget
from zettcode.tui.render import Style, blend, display_width, truncate

#: Rows the panel asks the shell for: a blank, the title, a blank, the three rows, a blank, the line that says what
#: the marked row does, and the keys.
ROWS = 10

#: The first row of the list, counted from the top of the panel.
LIST_TOP = 3

NAME_WIDTH = 12
WORD_WIDTH = 5
HINT = "\u2191 \u2193 row \u00b7 \u2190 \u2192 switch \u00b7 enter save and close \u00b7 esc cancel"
HINT_EXPORT = "\u2191 \u2193 row \u00b7 enter export and close \u00b7 esc cancel"


class MonitorPage(Widget):
    """Choose whether the session is recorded and whether images are kept, or export what was recorded.

    Shape::

        Monitor                                   ● recording · 12 calls (not applied)

        ▸ Recording   ━━━━━━━━●  on     Record every model call of this session
          Images      ●────────  off    Keep image data in the records
          Export      ↵ enter           Write 12 calls to an HTML file
        ...
        Recording: record every model call of this session
        ↑ ↓ row · ← → switch · enter save and close · esc cancel

    Left, Right and Space move the switches but change nothing yet. Enter on a switch row applies both switches and
    closes the panel; Enter on the Export row writes the report, applies the switches too, and closes it. Escape
    closes without applying anything. An export that cannot be done (nothing is recorded yet) keeps the panel open
    and says why on the line above the keys.

    Args:
        recording: Whether the session is recorded now.
        images: Whether image data is kept in the records now.
        count: Called for the number of calls recorded so far, each time the panel is drawn.
        on_apply: Receives the recording and image switches as they stand when the reader confirms.
        on_export: Writes the report and returns the line to say about it; raises ``ValueError`` with a reason.
        on_close: Called when the panel should go away, after a confirm, an export or a cancel.
        on_done: Receives a line to show the reader after the panel has closed, and whether it reports an export.
    """

    def __init__(
        self,
        *,
        recording: bool,
        images: bool,
        count: Callable[[], int],
        on_apply: Callable[[bool, bool], None],
        on_export: Callable[[], str],
        on_close: Callable[[], None],
        on_done: Callable[[str, bool], None] = lambda _said, _exported: None,
    ) -> None:
        super().__init__()
        self.start = (recording, images)
        self.recording = recording
        self.images = images
        self.count = count
        self.on_apply = on_apply
        self.on_export = on_export
        self.on_close = on_close
        self.on_done = on_done
        #: The row the marker is on: 0 recording, 1 images, 2 export.
        self.mark = 0
        #: Why the last export did not happen, shown until the marker moves.
        self.error = ""

    @property
    def focusable(self) -> bool:
        return True

    @property
    def changed(self) -> bool:
        """Return whether a switch is anywhere but where it started."""
        return (self.recording, self.images) != self.start

    def capture_event(self, event: object, host: Host) -> bool:
        """Take Escape before the focused widget can: it closes and applies nothing."""
        if pressed(event) == "escape":
            self.on_close()
            return True
        return False

    def set_switch(self, row: int, value: bool) -> None:
        """Set the switch of a row (0 or 1); it is only applied when the reader confirms."""
        if row == 0:
            self.recording = value
        elif row == 1:
            self.images = value

    def _flip(self, row: int) -> None:
        if row in (0, 1):
            self.set_switch(row, not (self.recording if row == 0 else self.images))

    def confirm(self) -> None:
        """Do what Enter does on the marked row, then close; an export that fails keeps the panel open."""
        exported = self.mark == 2
        if exported:
            try:
                said = self.on_export()
            except ValueError as error:
                self.error = str(error)
                return
        else:
            said = self._summary()
        if self.changed:
            self.on_apply(self.recording, self.images)
        self.on_close()
        self.on_done(said, exported)

    def _summary(self) -> str:
        return f"monitor: recording {'on' if self.recording else 'off'}, images {'on' if self.images else 'off'}"

    def handle(self, event: object, host: Host) -> bool:
        """Up and Down move the marker, Left, Right and Space move a switch, Enter confirms."""
        if isinstance(event, MouseEvent):
            return self._handle_mouse(event)
        match pressed(event):
            case "up" | "backtab":
                self.mark, self.error = (self.mark - 1) % 3, ""
            case "down" | "tab":
                self.mark, self.error = (self.mark + 1) % 3, ""
            case "left":
                self.set_switch(self.mark, False)
            case "right":
                self.set_switch(self.mark, True)
            case " ":
                self._flip(self.mark)
            case "enter":
                self.confirm()
            case _:
                return False
        return True

    def _handle_mouse(self, event: MouseEvent) -> bool:
        """Mark the row under a click; a click on a switch moves it and a click on Export exports."""
        if event.action is not MouseAction.DOWN:
            return False
        row = event.y - (self.rect.y + LIST_TOP)
        if not 0 <= row < 3:
            return False
        self.mark, self.error = row, ""
        if row == 2:
            self.confirm()
        elif self._switch_column() <= event.x < self._switch_column() + SWITCH_WIDTH + 1 + WORD_WIDTH:
            self._flip(row)
        return True

    def _switch_column(self) -> int:
        return self.rect.x + 2 + 2 + NAME_WIDTH

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
        canvas.draw_text(x, self.rect.y + 1, "Monitor", bold, max_width=room)
        calls = self.count()
        noun = "call" if calls == 1 else "calls"
        state = f"\u25cf recording \u00b7 {calls} {noun}" if self.recording else f"\u25cb off \u00b7 {calls} {noun}"
        if self.changed:
            state += " (not applied)"
        canvas.draw_text(
            self.rect.right - 2 - display_width(state),
            self.rect.y + 1,
            state,
            Style(
                foreground=theme.accent if self.changed or self.recording else theme.muted,
                background=surface,
                bold=self.changed,
            ),
            max_width=room,
        )
        groove = blend(theme.muted, surface, 0.55)
        rows = (
            ("Recording", self.recording, "Record every model call of this session"),
            ("Images", self.images, "Keep image data in the records; off keeps only an [image] marker"),
            ("Export", None, f"Write {calls} {noun} to an HTML file in the workspace"),
        )
        for index, (name, value, summary) in enumerate(rows):
            y = self.rect.y + LIST_TOP + index
            marked = index == self.mark
            if marked:
                canvas.draw_text(x, y, "\u25b8", Style(foreground=theme.accent, background=surface, bold=True))
            lit = value is not False
            name_style = bold if marked else Style(foreground=theme.text if lit else quiet, background=surface)
            canvas.draw_text(x + 2, y, name, name_style, max_width=NAME_WIDTH)
            start = self._switch_column()
            if value is not None:
                draw_switch(canvas, theme, y, start, 1.0 if value else 0.0, groove)
                canvas.draw_text(
                    start + SWITCH_WIDTH + 1,
                    y,
                    "on" if value else "off",
                    Style(foreground=theme.accent if value else quiet, background=surface),
                )
            else:
                canvas.draw_text(start, y, "\u21b5 enter", Style(foreground=theme.accent, background=surface))
            text_at = start + SWITCH_WIDTH + 1 + WORD_WIDTH + 1
            left = self.rect.right - 2 - text_at
            if left >= 18:
                canvas.draw_text(
                    text_at,
                    y,
                    truncate(summary, left),
                    Style(foreground=blend(theme.muted, surface, 0.15), background=surface),
                    max_width=left,
                )
        name, _, summary = rows[self.mark]
        line = self.error or f"{name}: {summary}"
        style = Style(foreground=theme.error, background=surface) if self.error else muted
        canvas.draw_text(x, self.rect.bottom - 2, truncate(line, room), style, max_width=room)
        hint = HINT_EXPORT if self.mark == 2 else HINT
        canvas.draw_text(x, self.rect.bottom - 1, truncate(hint, room), muted, max_width=room)
