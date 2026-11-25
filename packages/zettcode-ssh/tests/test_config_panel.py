"""SSH aliases are selectable; the panel keeps the plugin panels' shape and offers both sign-ins."""

from types import SimpleNamespace

import pytest

from zettcode.plugin_api import MouseAction, MouseEvent, PasteEvent, TextEvent
from zettcode.ssh.config import host_aliases
from zettcode.ssh.panel import CONNECT, HOST, LOCAL, PASSWORD, ROWS, SIGN_IN, SSHPage
from zettcode.ssh.transport import Target
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
    applied = []

    async def apply(target, password):
        applied.append((target, password))

    widget = SSHPage(
        target=None,
        status=lambda: "not connected \u00b7 full",
        on_apply=apply,
        on_close=lambda: None,
        aliases=aliases,
    )
    return widget, applied


def test_select_host_keyboard_and_manual_choice():
    widget, _ = page(("build", "production"))
    host = SimpleNamespace(invalidate=lambda: None)
    assert widget.choosing
    widget.handle(KeyEvent(key="down"), host)
    widget.handle(KeyEvent(key="enter"), host)
    assert widget.values[0] == "production" and widget.mark == 1 and not widget.choosing
    widget.handle(KeyEvent(key="f2"), host)
    widget.handle(KeyEvent(key="down"), host)
    widget.handle(KeyEvent(key="enter"), host)
    assert widget.mark == 0 and not widget.choosing


def test_render_matches_the_other_panels_and_boxes_no_field():
    widget, _ = page(("build", "production"))
    harness = Harness(widget, width=80, height=ROWS)
    assert "2 configured host(s) in ~/.ssh/config" in harness.render().text
    widget.handle(MouseEvent(x=3, y=4, action=MouseAction.DOWN), harness.app)
    assert widget.values[0] == "production"
    text = harness.render().text
    # The title and its state, the rows with their marker, the sentence, and the keys: the plugin-panel shape.
    assert "SSH" in text and "off" in text
    widget.target = Target("production", "/remote")
    assert "not connected \u00b7 full" in harness.render().text
    assert "\u25b8 " in text and "Host" in text and "Workspace" in text and "Sign in" in text and "Password" in text
    assert "Workspace: the absolute remote directory every remote tool works in" in text
    widget.mark = 0
    assert "Host: an alias from ~/.ssh/config, or user@hostname typed by hand" in harness.render().text
    assert "\u2191 \u2193 row" in text and "esc cancel" in text
    assert "\u250c" not in text and "\u2502" not in text  # boxes belong to the shell's forms, not a plugin panel


def test_key_and_password_sign_in():
    widget, applied = page()
    host = SimpleNamespace(invalidate=lambda: None)
    assert widget.auth == "key"
    widget.mark = SIGN_IN
    widget.handle(KeyEvent(key="right"), host)
    assert widget.auth == "password"
    widget.handle(KeyEvent(key="left"), host)
    assert widget.auth == "key"
    # Typing in the password row selects password sign-in without a separate toggle.
    widget.mark = PASSWORD
    for char in "sec":
        widget.handle(TextEvent(text=char), host)
    assert widget.auth == "password" and widget.password == "sec"


def test_password_is_masked_and_never_reaches_a_plain_field():
    widget, _ = page()
    widget.values = ["alias", "/remote", ""]
    widget.auth, widget.password = "password", "hunter2"
    harness = Harness(widget, width=80, height=ROWS)
    text = harness.render().text
    assert "\u2022\u2022\u2022\u2022\u2022\u2022\u2022" in text
    assert "hunter2" not in text
    target = widget.target_now()
    assert target.auth == "password" and target.user is None
    assert "hunter2" not in repr(target) and "hunter2" not in repr(target.export())


def test_an_empty_row_shows_its_whole_placeholder():
    widget, _ = page()
    text = Harness(widget, width=80, height=ROWS).render().text
    assert "(type a host)" in text
    assert "(remote path)" in text and "(from config)" in text
    widget.auth = "password"
    text = Harness(widget, width=80, height=ROWS).render().text
    assert "(required)" in text


def test_space_toggles_the_sign_in_and_left_right_set_it():
    widget, _ = page()
    host = SimpleNamespace(invalidate=lambda: None)
    widget.mark = SIGN_IN
    widget.handle(TextEvent(text=" "), host)
    assert widget.auth == "password"
    widget.handle(TextEvent(text=" "), host)
    assert widget.auth == "key"
    widget.handle(KeyEvent(key="space"), host)
    assert widget.auth == "password"
    widget.handle(KeyEvent(key="left"), host)
    assert widget.auth == "key"


def test_an_unmarked_value_shows_its_start_not_its_end():
    path = "/very/long/path/" + "x" * 60
    widget, _ = page()
    widget.target = Target("build", path)
    widget.values = ["build", path, ""]
    widget.cursors = [5, len(path), 0]
    widget.mark = 0
    text = Harness(widget, width=80, height=ROWS).render().text
    assert "/very/long/path/" in text
    assert "x" * 40 not in text


def test_a_value_that_fits_keeps_its_note_and_its_whole_text():
    path = "/srv/very/deep/project-directory-name"
    widget, _ = page()
    widget.target = Target("build-host-1", path)
    widget.values = ["build-host-1", path, ""]
    text = Harness(widget, width=100, height=ROWS).render().text
    assert path in text, "a value that fits is drawn whole, from its first character"
    assert "remote working directory" in text


def test_a_narrow_panel_still_shows_the_value_it_edits():
    widget, _ = page()
    widget.values = ["build", "/srv/project", ""]
    widget.cursors = [5, 12, 0]
    text = Harness(widget, width=36, height=ROWS).render().text
    row = next(line for line in text.splitlines() if "Workspace" in line)
    assert "/srv/project"[:13] in row, row
    assert "remote working directory" not in row, "the note gives way to the value on a narrow panel"


def test_a_click_on_a_row_that_is_not_drawn_is_ignored():
    widget, _ = page()
    small = Harness(widget, width=70, height=5)
    before = widget.mark
    assert widget.handle(MouseEvent(x=30, y=4, action=MouseAction.DOWN), small.app) is False
    assert widget.mark == before
    assert widget._visible() == 0


def test_the_sign_in_word_is_never_painted_over_by_its_note():
    def row(width, auth):
        widget, _ = page()
        widget.target = Target("b", "/s")
        widget.auth = auth
        text = Harness(widget, width=width, height=ROWS).render().text
        return next(line for line in text.splitlines() if "Sign in" in line)

    for width in range(44, 70):
        for auth, word, note in (
            ("key", "key/agent", "no password needed"),
            ("password", "password", "asks for a password"),
        ):
            line = row(width, auth)
            if note not in line:
                continue
            start = line.index(note)
            assert line[:start].endswith(" "), (width, auth, line)
            at = line.index(word, line.index("Sign in"))
            assert at + len(word) <= start, (width, auth, line)


def test_a_focused_value_that_fills_its_room_keeps_its_last_character():
    for size in (19, 20, 30, 37):
        widget, _ = page()
        widget.values = ["h" * size, "/s", ""]
        widget.cursors = [size, 2, 0]
        widget.mark = HOST
        text = Harness(widget, width=80, height=ROWS).render().text
        row = next(line for line in text.splitlines() if "h" in line)
        # The note begins with "select"; what is before it is the value as drawn.
        assert row.split("select")[0].count("h") == size, (size, row)


def test_a_short_terminal_scrolls_to_the_marked_row():
    widget, _ = page()
    widget.mark = LOCAL
    text = Harness(widget, width=70, height=6).render().text
    assert "Disconnect" in text and "esc cancel" in text
    assert "Host:" not in text, "the sentence gives way to the rows, never painted over them"


def test_the_switch_turns_the_way_the_keys_say():
    widget, _ = page()
    host = SimpleNamespace(invalidate=lambda: None)
    widget.mark = SIGN_IN
    assert widget.rail.selected == 0 and widget.auth == "key"
    widget.handle(KeyEvent(key="right"), host)
    assert widget.rail.selected == 1 and widget.auth == "password"
    assert widget.rail.position(widget._now() + 1.0) == 1.0, "the knob travels to the option on the right"
    widget.handle(KeyEvent(key="left"), host)
    assert widget.rail.selected == 0
    assert widget.rail.position(widget._now() + 1.0) == 0.0


def test_the_edited_row_looks_like_a_field():
    widget, _ = page()
    widget.mark = HOST
    assert "\u258f" in Harness(widget, width=80, height=ROWS).render().text
    widget.mark = CONNECT
    assert "\u258f" not in Harness(widget, width=80, height=ROWS).render().text


async def test_connecting_is_a_working_notice_not_an_error():
    import asyncio

    gate = asyncio.Event()

    async def slow(target, password):
        await gate.wait()

    widget = SSHPage(
        target=None,
        status=lambda: "off",
        on_apply=slow,
        on_close=lambda: None,
    )
    widget.values = ["alias", "/remote", ""]
    widget.mark = CONNECT
    widget.confirm(SimpleNamespace(invalidate=lambda: None))
    await asyncio.sleep(0)
    assert widget.error == "" and widget.notice == "Connecting"
    gate.set()
    await widget.pending


def test_the_caret_is_visible_on_a_wide_character():
    widget, _ = page()
    widget.values = ["\u4f8b\u5b50\u76ee\u9304/\u6df1\u5c64", "/srv", ""]
    widget.cursors = [1, 4, 0]
    widget.mark = HOST
    snap = Harness(widget, width=80, height=ROWS).render()
    row = widget.rect.y + 3
    accent = [
        span
        for span in snap.styled[row]
        if span.style.background is not None and span.style.background == widget.theme.accent
    ]
    assert accent and "".join(span.text for span in accent) == "\u5b50"


def test_connecting_dots_follow_the_clock_not_the_frame_count():
    widget, _ = page()
    widget.notice = "Connecting"
    widget._started = 0.0
    assert widget.notice_now(0.0) == "Connecting."
    assert widget.notice_now(0.5) == "Connecting.."
    assert widget.notice_now(0.9) == "Connecting..."
    assert widget.notice_now(1.3) == "Connecting."


async def test_closing_the_panel_cancels_a_probe_in_flight():
    import asyncio

    gate = asyncio.Event()
    finished = []

    async def slow(target, password):
        await gate.wait()
        finished.append(target)

    widget = SSHPage(target=None, status=lambda: "off", on_apply=slow, on_close=lambda: None)
    widget.values = ["alias", "/remote", ""]
    widget.mark = CONNECT
    widget.confirm(SimpleNamespace(invalidate=lambda: None))
    await asyncio.sleep(0)
    widget.on_unmount()
    await widget.pending  # the apply ends without applying anything
    assert widget.closed and not finished and widget.error == ""


async def test_a_second_escape_does_not_abort_the_password_cleanup():
    import asyncio

    from zettcode.ssh.transport import Transport

    transport = Transport(Target("alias", "/srv", None, "password"), password="s3cret")
    transport._environment()  # writes the askpass helper, as a connection would
    helper = transport._askpass
    assert helper is not None and helper.directory is not None
    directory = helper.directory

    async def slow_close():
        await asyncio.sleep(0.05)

    transport._close = slow_close
    task = asyncio.create_task(transport.aclose())
    await asyncio.sleep(0.01)
    task.cancel()
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert transport.password is None and helper.directory is None and not directory.exists()


def test_a_pasted_line_loses_its_newline():
    widget, _ = page()
    widget.handle(PasteEvent(text="build.local:2222\n"), SimpleNamespace(invalidate=lambda: None))
    assert widget.values[0] == "build.local:2222" and not widget.error


def test_connect_requires_a_password_before_anything_is_attempted():
    widget, applied = page()
    widget.values = ["alias", "/remote", "deploy"]
    widget.auth = "password"
    widget.mark = 5  # Connect
    widget.confirm(SimpleNamespace(invalidate=lambda: None))
    assert widget.error.startswith("Enter the password") and not applied and widget.pending is None


async def test_connect_applies_the_target_and_password_together():
    import asyncio

    widget, applied = page()
    widget.values = ["alias", "/remote", "deploy"]
    widget.auth, widget.password = "password", "s3cret"
    widget.mark = 5  # Connect
    widget.confirm(SimpleNamespace(invalidate=lambda: None))
    await asyncio.gather(widget.pending)
    assert applied == [(Target("alias", "/remote", "deploy", "password"), "s3cret")]


async def test_local_tools_row_disconnects():
    import asyncio

    widget, applied = page()
    widget.mark = LOCAL
    widget.confirm(SimpleNamespace(invalidate=lambda: None))
    await asyncio.gather(widget.pending)
    assert applied == [(None, "")]
