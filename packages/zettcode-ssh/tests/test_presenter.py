"""An ssh__ row is drawn by the shell's own presenter, once its name has been reduced to the local tool's."""

from zettcode.plugin_api import EntryKind, Presenter, Presenters, Span, Style, TextLine, ToolEntry
from zettcode.ssh.presenter import SSHToolNames
from zettcode.tui import DARK


class Local(Presenter[ToolEntry]):
    """Stands in for the shell's presenter: claims by the local tool name, as the real ones do."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.seen: list[str] = []

    def handle(self, entry, next):
        return self if getattr(entry, "tool", "") == self.name else next(entry)

    def lines(self, entry, width, theme, frame):
        self.seen.append(entry.tool)
        return [TextLine(), TextLine((Span(f"draw {entry.tool}", Style(foreground=theme.accent)),))]


def entry(tool: str = "ssh__read", **changes) -> ToolEntry:
    values = {"id": 1, "call_id": "c1", "tool": tool, "title": "ssh/read  src/main.py", "started_at": 0.0}
    values.update(changes)
    return ToolEntry(**values)  # type: ignore[arg-type]


def test_the_ssh_row_is_drawn_by_the_presenter_for_the_local_tool():
    local = Local("read")
    registry = Presenters((local, SSHToolNames()))
    row = entry()
    source = registry.block(row, 40, DARK, 0)
    assert row.tool == "ssh__read"
    assert registry.block(row, 40, DARK, 0) is source
    assert local.seen == ["read"], "the shell's read presenter drew it"
    assert "draw read" in "".join(span.text for span in source.line(1, 40).spans)


class Marker(Presenter[ToolEntry]):
    """A delegate that draws nothing; the test only checks which name it was handed."""

    def handle(self, entry, next):
        return self

    def lines(self, entry, width, theme, frame):
        return []


def test_only_our_names_are_renamed():
    untouched = entry(tool="read")
    SSHToolNames().handle(untouched, lambda item: Marker())
    assert untouched.tool == "read"

    ours = entry(tool="ssh__bash")
    seen = []

    def next(item):
        seen.append(item.tool)
        return Marker()

    SSHToolNames().handle(ours, next)
    assert ours.tool == "ssh__bash" and seen == ["ssh__bash"]
    assert ours.kind is EntryKind.TOOL
    assert SSHToolNames().tool_rendering_alias("ssh__bash").name == "bash"
    for name in ("read", "mcp__read", "other__read", "ssh__unknown"):
        assert SSHToolNames().tool_rendering_alias(name) is None
