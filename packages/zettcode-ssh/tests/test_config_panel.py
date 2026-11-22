"""SSH aliases are selectable; manual fields are visible and editable."""

from types import SimpleNamespace

from zettcode.plugin_api import MouseAction, MouseEvent
from zettcode.ssh.config import host_aliases
from zettcode.ssh.panel import ROWS, SSHPage
from zettcode.tui import KeyEvent
from zettcode.tui.testing import Harness


def test_aliases_include_multiple_hosts_comments_patterns_and_cycles(tmp_path):
    config = tmp_path / "config"
    included = tmp_path / "extra"
    included.write_text("Host included other\nInclude config\n", encoding="utf-8")
    config.write_text(
        "Host alpha beta # comment\nHost * *.example !excluded\n"
        "Include extra\nHost=equals\nHost = spaced\n"
        'Match exec "touch should-not-exist"\nInclude absent\n'
        'Host alpha "quoted-alias"\n',
        encoding="utf-8",
    )
    assert host_aliases(config) == ("alpha", "beta", "included", "other", "equals", "spaced", "quoted-alias")
    assert not (tmp_path / "should-not-exist").exists()
    assert host_aliases(tmp_path / "missing") == ()


def page(aliases=()):
    async def apply(target):
        pass

    return SSHPage(target=None, status=lambda: "off", on_apply=apply, on_close=lambda: None, aliases=aliases)


def test_select_host_keyboard_and_manual_choice():
    widget = page(("build", "production"))
    host = SimpleNamespace(invalidate=lambda: None)
    assert widget.choosing
    widget.handle(KeyEvent(key="down"), host)
    widget.handle(KeyEvent(key="enter"), host)
    assert widget.values[0] == "production" and widget.mark == 1 and not widget.choosing
    widget.handle(KeyEvent(key="f2"), host)
    widget.handle(KeyEvent(key="down"), host)
    widget.handle(KeyEvent(key="enter"), host)
    assert widget.mark == 0 and not widget.choosing


def test_render_fields_and_click_configured_alias():
    widget = page(("build", "production"))
    harness = Harness(widget, width=80, height=ROWS)
    assert "Choose a host from ~/.ssh/config" in harness.render().text
    widget.handle(MouseEvent(x=3, y=5, action=MouseAction.DOWN), harness.app)
    assert widget.values[0] == "production"
    text = harness.render().text
    assert "Host — type or paste" in text and "Remote workspace — type or paste" in text
    assert "┌" in text and "└" in text and "/absolute/remote/path" in text
    assert "F2: choose a configured host" in text
