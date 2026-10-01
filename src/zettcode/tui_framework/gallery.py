"""Preview every built-in widget as a frame that can be printed or paged through.

The gallery is headless by design: an entry is a name, a one-line summary, the
size it wants, and a factory that builds the widget. :func:`render_entry` mounts
one widget in a throwaway :class:`~zettcode.tui_framework.core.app.App` and
paints a single frame, and :func:`print_gallery` writes those frames to a
stream. That is what lets ``make demo-list`` show a component with no TTY and no
test harness in the way.

Previews are snapshots: a spinner shows one glyph and a toast one frame of its
countdown, because nothing ticks the clock in a one-shot render.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TextIO

from .core.app import App
from .core.events import KeyEvent
from .core.geometry import Point, Rect, Size
from .core.host import Host
from .core.screen import Screen
from .core.theme import DARK, Theme
from .core.widget import Widget
from .layout import Anchor, Border, HBox, Overlay, OverlaySlot, Padding, ScrollView, Slot, StaticLines, VBox
from .render import Canvas, ColorDepth, Span, Style, TextLine, encode_style
from .widgets import (
    Collapsible,
    Column,
    CompletionItem,
    CompletionPopup,
    Dialog,
    DialogAction,
    DiffView,
    ListItem,
    ListView,
    MarkdownView,
    ProgressBar,
    Rule,
    Spinner,
    StatusBar,
    Table,
    TaskPanel,
    Text,
    TextArea,
    Toast,
)

MARKDOWN_SAMPLE = """\
## Widget gallery

Prose wraps to the pane, and inline **bold**, `code`, and [links](https://example.com)
keep their own styling.

- bullet one
- bullet two

```python
def add(a, b):
    return a + b
```
"""

DIFF_BEFORE = """\
def total(items):
    value = 0
    for item in items:
        value = value + item
    return value
"""

DIFF_AFTER = """\
def total(items):
    return sum(item.price for item in items)
"""

SCROLL_LINES = tuple(f"line {index:02d}" for index in range(1, 21))

SIDEBAR = 30


@dataclass(frozen=True, slots=True)
class GalleryEntry:
    """One component in the gallery.

    Attributes:
        name: Target name, used by ``make demo-<name>`` and the script argument.
        summary: One line describing what the frame shows.
        size: Frame size in cells; the widget is laid out into exactly this
            rectangle, so an entry shows its natural shape.
        build: Builds a fresh widget per render, so state never leaks between
            previews and a factory may preconfigure a widget before it is mounted.
    """

    name: str
    summary: str
    size: Size
    build: Callable[[], Widget]


def _textarea() -> TextArea:
    """Return the composer sample, pre-filled so wrapping and the prompt show."""
    area = TextArea(prompt="\u203a ", placeholder="ask anything", completions=("/clear", "/quit"))
    area.set_text("explain the diff widget\nand keep it short")
    return area


def _task_panel() -> TaskPanel:
    """Return the plan panel with one task in each state."""
    panel = TaskPanel()
    panel.set_tasks(
        (("completed", "read the renderer"), ("processing", "preview widgets"), ("pending", "run make check"))
    )
    return panel


def _layout_sample() -> Widget:
    """Return a frame exercising boxes, spacing, borders, and anchored overlays."""
    left = VBox(
        [
            Slot(Text("VBox slot 1", bold=True), size=1),
            Slot(Text("VBox slot 2", muted=True), size=1),
            Slot(Padding(Text("Padding(1)"), 1), flex=1),
        ]
    )
    right = Overlay(
        [
            OverlaySlot(
                Text("center"),
                Anchor(horizontal="center", vertical="center"),
            )
        ]
    )
    return HBox(
        [
            Slot(Border(left, title=" VBox + Padding "), flex=1),
            Slot(Border(right, title=" Overlay center "), flex=1),
        ]
    )


GALLERY: tuple[GalleryEntry, ...] = (
    GalleryEntry(
        "text",
        "Text and Rule: bold, muted, wrapping, and right alignment",
        Size(46, 4),
        lambda: VBox(
            [
                Slot(Text("bold heading", bold=True), size=1),
                Slot(Rule(), size=1),
                Slot(Text("muted caption that wraps across the remaining rows", muted=True), flex=1),
            ]
        ),
    ),
    GalleryEntry(
        "status_bar",
        "StatusBar: one row, left segment plus right segment",
        Size(46, 1),
        lambda: StatusBar("  zettcode", "openai/gpt-5  "),
    ),
    GalleryEntry("spinner", "Spinner: animated glyph with a label", Size(24, 1), lambda: Spinner("working")),
    GalleryEntry(
        "progress_bar",
        "ProgressBar: determinate bar with a label",
        Size(30, 1),
        lambda: ProgressBar(0.42, label="build"),
    ),
    GalleryEntry(
        "list",
        "ListView: marker, description, and a disabled row",
        Size(34, 4),
        lambda: ListView(
            [
                ListItem("a", label="alpha", description="first"),
                ListItem("b", label="beta", description="second"),
                ListItem("c", label="gamma", disabled=True),
                ListItem("d", label="delta", description="fourth"),
            ]
        ),
    ),
    GalleryEntry(
        "table",
        "Table: header rule, wrapping cells, per-column alignment",
        Size(42, 6),
        lambda: Table(
            [Column("Name"), Column("Files", align="right"), Column("State", align="center")],
            [["parser", "12", "done"], ["renderer", "7", "wip"], ["tests", "31", "done"]],
        ),
    ),
    GalleryEntry(
        "diff",
        "DiffView: hunk header, line numbers, word-level emphasis",
        Size(58, 9),
        lambda: DiffView.between(DIFF_BEFORE, DIFF_AFTER, context=2),
    ),
    GalleryEntry(
        "markdown",
        "MarkdownView: headings, bullets, inline spans, fenced code",
        Size(46, 12),
        lambda: MarkdownView(MARKDOWN_SAMPLE, follow_tail=False),
    ),
    GalleryEntry("textarea", "TextArea: prompt, wrapping, and a pre-filled draft", Size(46, 4), _textarea),
    GalleryEntry(
        "completion",
        "CompletionPopup: command column, muted descriptions, banded selection",
        Size(34, 5),
        lambda: CompletionPopup(
            [
                CompletionItem("/clear", description="clear the transcript"),
                CompletionItem("/quit", description="exit"),
                CompletionItem("/theme", description="switch palette"),
            ],
            max_height=3,
        ),
    ),
    GalleryEntry(
        "dialog",
        "Dialog: bordered body with a row of selectable actions",
        Size(38, 9),
        lambda: Dialog(
            Text("rm -rf build/"),
            title="Run this command?",
            actions=(DialogAction("Run"), DialogAction("Always"), DialogAction("Abort")),
        ),
    ),
    GalleryEntry(
        "collapsible",
        "Collapsible: header marker plus an expanded body",
        Size(40, 5),
        lambda: Collapsible("Thinking", Text("Checked the renderer, then the keymap."), expanded=True),
    ),
    GalleryEntry(
        "toast",
        "Toast: level-coloured notice with a frame",
        Size(32, 3),
        lambda: Toast("saved to disk", level="success"),
    ),
    GalleryEntry("tasks", "TaskPanel: one row per task, coloured by state", Size(38, 4), _task_panel),
    GalleryEntry(
        "scroll",
        "ScrollView: virtualized window over already-wrapped lines",
        Size(30, 5),
        lambda: ScrollView(StaticLines([TextLine((Span(line),)) for line in SCROLL_LINES]), follow_tail=False),
    ),
    GalleryEntry("layout", "VBox, HBox, Padding, Border, and a centred Overlay", Size(48, 8), _layout_sample),
)


def select_entries(names: Sequence[str] = ()) -> tuple[GalleryEntry, ...]:
    """Return the entries named by ``names``, or every entry when it is empty.

    Args:
        names: Component names as written after ``make demo-``; an empty
            sequence means the whole gallery.

    Raises:
        ValueError: One of the names is unknown; the message lists the valid
            ones so a typo is obvious on the command line.
    """
    if not names:
        return GALLERY
    known = {entry.name: entry for entry in GALLERY}
    chosen: list[GalleryEntry] = []
    for name in names:
        entry = known.get(name)
        if entry is None:
            options = ", ".join(known)
            raise ValueError(f"Unknown component {name!r}. Available: {options}")
        chosen.append(entry)
    return tuple(chosen)


def render_entry(entry: GalleryEntry, *, theme: Theme = DARK) -> Canvas:
    """Mount one entry's widget and return its single painted frame.

    Args:
        entry: Component to render; its factory is called once per invocation.
        theme: Palette the preview is painted with.
    """
    app = App(entry.build(), width=entry.size.width, height=entry.size.height, theme=theme)
    app.mount()
    return app.render()


def frame_text(canvas: Canvas, *, color: bool = True, depth: ColorDepth = ColorDepth.TRUECOLOR) -> str:
    """Return a canvas as printable text, optionally with its colours.

    Args:
        canvas: Frame to flatten.
        color: Emit SGR sequences per styled run; when False the frame is plain
            text, which is what a pipe or a golden file wants.
        depth: Colour encoding used when ``color`` is True.
    """
    rows = [row_text(canvas, index, color=color, depth=depth) for index in range(canvas.height)]
    while rows and not rows[-1]:
        rows.pop()
    return "\n".join(rows)


def row_text(canvas: Canvas, index: int, *, color: bool = True, depth: ColorDepth = ColorDepth.TRUECOLOR) -> str:
    """Return one canvas row, trimmed of trailing padding.

    Args:
        canvas: Frame that owns the row.
        index: Row to read; out-of-range indexes render as empty.
        color: Wrap each styled run in its SGR sequence.
        depth: Colour encoding used when ``color`` is True.
    """
    if not 0 <= index < canvas.height:
        return ""
    cells = [cell for cell in canvas.cells[index] if not cell.continuation]
    plain = "".join(cell.character or " " for cell in cells).rstrip()
    if not color or not plain:
        return plain
    parts: list[str] = []
    pending = ""
    style: Style | None = None
    for cell in cells:
        if len(pending) >= len(plain):
            break
        if cell.style != style and pending:
            parts.append(encode_style(style, depth) + pending)
            pending = ""
        style = cell.style
        pending += cell.character or " "
    if pending:
        parts.append(encode_style(style, depth) + pending)
    # SGR 0 closes each row so a colour cannot leak into the next line.
    return "".join(parts) + "\x1b[0m"


def print_gallery(
    entries: Sequence[GalleryEntry] | None = None,
    *,
    color: bool = True,
    stream: TextIO | None = None,
    theme: Theme = DARK,
) -> None:
    """Print one caption and one frame per entry.

    Args:
        entries: Components to print; defaults to the whole gallery.
        color: Paint each frame with its palette.
        stream: Sink to write to; defaults to ``sys.stdout`` at call time so a
            caller that swapped it out (a test, a log file) is honored. A pipe
            usually wants ``color=False``.
        theme: Palette the previews are painted with.
    """
    sink = sys.stdout if stream is None else stream
    for entry in GALLERY if entries is None else entries:
        print(f"### {entry.name} - {entry.summary}", file=sink)
        print(frame_text(render_entry(entry, theme=theme), color=color), file=sink)
        print(file=sink)


class GalleryRoot(Widget):
    """Root that hands the whole application rectangle to the browser body."""

    def __init__(self, body: Widget) -> None:
        """Keep the body this root exists to place.

        Args:
            body: The browser's box tree, laid out at the full size of the app.
        """
        super().__init__()
        self.body = body

    @property
    def children(self) -> tuple[Widget, ...]:
        """Expose the single body widget."""
        return (self.body,)

    def layout(self, rect: Rect) -> None:
        """Give the body the full application rectangle."""
        super().layout(rect)
        self.body.layout(rect)

    def render(self, canvas: Canvas) -> None:
        """Paint the body into the shared canvas."""
        self.body.render(canvas)

    def cursor(self) -> Point | None:
        """Forward the cursor request to the body."""
        return self.body.cursor()


class Spacer(Widget):
    """Hold a column open so a sibling starts further along the row."""


class GalleryBrowser:
    """Interactive browser: an index on the left, a live preview on the right.

    The preview is a screen layer above the index rather than a swapped-in
    child, because pushing a screen is what mounts a fresh widget subtree and
    attaches it to the app. ``_show_preview`` therefore closes the previous
    layer before opening the next one, which keeps exactly one preview mounted
    while the highlight moves.

    The keyboard stays with the index until Enter is pressed, so the arrow keys
    keep browsing instead of being absorbed by whichever preview happens to be
    focusable. Escape hands the keyboard back.
    """

    def __init__(self, entries: Sequence[GalleryEntry] = GALLERY, *, theme: Theme = DARK) -> None:
        """Build the index, the preview mechanism, and their key bindings.

        Args:
            entries: Components to offer, in index order.
            theme: Palette shared by the index and every preview.
        """
        self.entries = tuple(entries)
        self.preview_screen: Screen | None = None
        self.list = ListView(
            [ListItem(entry.name, label=entry.name, description=entry.summary) for entry in self.entries],
            on_select=self._enter_preview,
            on_highlight=self._show_preview,
        )
        self.status = StatusBar(self._status)
        index = VBox(
            [
                Slot(self.list, flex=1),
                Slot(Rule(), size=1),
                Slot(self.status, size=1),
            ]
        )
        body = VBox(
            [
                Slot(StatusBar("components", self._hint), size=1),
                Slot(Rule(), size=1),
                # The index owns a fixed column so the preview, which is
                # anchored to the right edge of its own screen, cannot overlap it.
                Slot(HBox([Slot(index, size=SIDEBAR)]), flex=1),
            ]
        )
        self.app = App(GalleryRoot(body), theme=theme)
        self._install_keymap()
        self.app.mount()
        self._show_preview(self.list.current)

    def run(self) -> None:
        """Own the terminal until the user quits."""
        from .runner import TerminalRunner

        asyncio.run(TerminalRunner(self.app).run())

    def _install_keymap(self) -> None:
        """Bind the browser keys: Ctrl-C and q quit, Escape steps back."""
        self.app.commands.add("quit", lambda event, host: (host.exit(), True)[1])
        self.app.commands.add("leave_preview", self._leave_preview)
        self.app.keymap.bind("ctrl_c", "quit", priority="capture")
        # q only quits from the index: inside a preview it belongs to the widget
        # being driven, such as a text area the user is typing into.
        self.app.keymap.bind("q", "quit", priority="capture", when=self._at_index)
        self.app.keymap.bind("escape", "leave_preview", priority="capture", when=self._in_preview)

    def _at_index(self) -> bool:
        """Return whether the index itself holds the keyboard."""
        return self.app.focused_widget() is self.list

    def _in_preview(self) -> bool:
        """Return whether the keyboard is inside a preview widget."""
        return self.preview_screen is not None and not self._at_index()

    def _leave_preview(self, event: KeyEvent, host: Host) -> bool:
        """Hand the keyboard back to the index."""
        self.app.focus(self.list)
        return True

    def _current(self) -> GalleryEntry | None:
        """Return the entry highlighted in the index."""
        item = self.list.current
        if item is None:
            return None
        return next((entry for entry in self.entries if entry.name == item.value), None)

    def _status(self) -> str:
        """Label the previewed component and what it demonstrates."""
        entry = self._current()
        return f"  {entry.name}: {entry.summary}" if entry else "  components"

    def _hint(self) -> str:
        """List the keys worth knowing while the index has focus."""
        return "  up/down browse \u00b7 enter interact \u00b7 esc back \u00b7 q quit  "

    def _show_preview(self, item: ListItem | None) -> None:
        """Replace the preview layer with the newly highlighted component.

        Args:
            item: Row the index just highlighted; ignored when it is unknown.
        """
        entry = next((entry for entry in self.entries if entry.name == item.value), None) if item else None
        if entry is None:
            return
        if self.preview_screen is not None:
            self.app.pop_screen()
        panel = Border(entry.build(), title=f" {entry.name} ")
        overlay = Overlay([OverlaySlot(panel, Anchor(horizontal="end", vertical="center", offset_x=-1))])
        # The spacer keeps the overlay's rectangle to the right of the index, so
        # an anchor at "end" resolves inside the free area rather than over it.
        region = HBox([Slot(Spacer(), size=SIDEBAR), Slot(overlay, flex=1)])
        self.preview_screen = self.app.push_screen(Screen(region, name="preview"))
        # push_screen would hand the keyboard to a focusable preview; browsing
        # stays on the index until Enter is pressed.
        self.app.focus(self.list)

    def _enter_preview(self, item: ListItem) -> None:
        """Move the keyboard into the preview so the widget can be driven."""
        if self.preview_screen is not None:
            self.app.focus_next()


def main(argv: Sequence[str] | None = None) -> int:
    """Render the requested components, returning the process exit code.

    Args:
        argv: Arguments without the program name; ``None`` reads ``sys.argv``.

    Returns:
        0 on success, 2 when a requested name is unknown, so a typo after
        ``make demo-`` fails loudly instead of printing nothing.
    """
    parser = argparse.ArgumentParser(prog="make demo", description="Preview the TUI framework widgets.")
    parser.add_argument("names", nargs="*", help="component names to print; omit to browse or print all")
    parser.add_argument("--list", action="store_true", help="list component names and exit")
    parser.add_argument("--no-color", action="store_true", help="print plain text frames")
    parser.add_argument(
        "--print", dest="print_all", action="store_true", help="print every component instead of browsing"
    )
    args = parser.parse_args(argv)

    if args.list:
        for entry in GALLERY:
            print(f"{entry.name:<12} {entry.summary}")
        return 0

    try:
        entries = select_entries(args.names)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2

    # Named components always print: `make demo-list` is the quick "show me this
    # one" path, while the bare command browses when it owns a terminal.
    browsing = not args.names and not args.print_all
    if browsing and sys.stdin.isatty() and sys.stdout.isatty():
        GalleryBrowser(entries).run()
        return 0

    print_gallery(entries, color=not args.no_color and sys.stdout.isatty())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
