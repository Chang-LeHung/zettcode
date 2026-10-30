from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from zett_agent.messages import AssistantMessage, SystemMessage, ToolCall, UserMessage
from zett_agent.model import ModelEvent, ModelRequest, ModelResponse, ModelUsage
from zettcode.app.commands import CommandContext

from zettcode_monitor import MonitorPlugin, render_report
from zettcode_monitor.recorder import MonitorExtension

SESSION = "s-1"


def _context(session_id: str = SESSION):
    return SimpleNamespace(config=SimpleNamespace(session_id=session_id))


def _request() -> ModelRequest:
    return ModelRequest(messages=[SystemMessage(content="be brief"), UserMessage(content="hi </script>")])


async def _call(ext: MonitorExtension, *, fail: bool = False):
    async def call_next(request):
        if fail:
            raise RuntimeError("boom")
        reply = AssistantMessage(content="hello", tool_calls=[ToolCall(id="1", name="x", arguments={"a": 1})])
        yield ModelEvent.text("hel")
        yield ModelEvent.completed(ModelResponse(reply, usage=ModelUsage(input_tokens=5, output_tokens=2)))

    return [e async for e in ext.on_model_request(_context(), _request(), call_next)]


async def test_off_by_default_records_nothing(tmp_path):
    ext = MonitorExtension(tmp_path)
    assert len(await _call(ext)) == 2
    assert not (tmp_path / SESSION).exists()


async def test_records_each_call_and_remembers_state(tmp_path):
    ext = MonitorExtension(tmp_path)
    ext.set_enabled(SESSION, True)
    await _call(ext)
    await _call(ext)
    calls = ext.calls(SESSION)
    assert [c["number"] for c in calls] == [1, 2]
    assert calls[0]["request"]["messages"][1]["text"] == "hi </script>"
    assert calls[0]["response"]["message"]["tool_calls"][0]["name"] == "x"
    assert calls[0]["response"]["usage"]["input_tokens"] == 5
    # a fresh extension (a resumed process) reads the switch from disk and keeps numbering
    again = MonitorExtension(tmp_path)
    assert again.enabled(SESSION)
    await _call(again)
    assert len(again.calls(SESSION)) == 3 and again.calls(SESSION)[-1]["number"] == 3
    again.set_enabled(SESSION, False)
    assert not MonitorExtension(tmp_path).enabled(SESSION)


async def test_duration_starts_at_before_model(tmp_path):
    import time

    ext = MonitorExtension(tmp_path)
    ext.set_enabled(SESSION, True)
    await ext.before_model(_context(), _request())  # type: ignore[arg-type]
    time.sleep(0.05)  # work other before_model hooks do, which the terminal's rate counts too
    await _call(ext)
    assert ext.calls(SESSION)[0]["duration_ms"] >= 50
    await _call(ext)  # no stamp left over: the next call times itself
    assert ext.calls(SESSION)[1]["duration_ms"] < 50


async def test_server_tools_and_message_fields_are_recorded(tmp_path):
    from zett_agent.model import (
        ServerToolCall,
        ServerToolDefinition,
        ServerToolInputDelta,
        ServerToolResult,
        ToolDefinition,
    )

    ext = MonitorExtension(tmp_path)
    ext.set_enabled(SESSION, True)
    request = ModelRequest(
        messages=[UserMessage(content="search")],
        tools=[ToolDefinition(name="t", description="d", parameters={}, deferred=True)],
        server_tools=[ServerToolDefinition(type="web_search", configuration={"max_uses": 2})],
    )

    async def call_next(_request):
        yield ModelEvent.server_tool_started(ServerToolCall(id="s1", name="web_search"))
        yield ModelEvent.server_tool_input(ServerToolInputDelta(call_id="s1", delta='{"q":'))
        yield ModelEvent.server_tool_input(ServerToolInputDelta(call_id="s1", delta='"zett"}'))
        yield ModelEvent.server_tool_completed(ServerToolResult(call_id="s1", name="web_search", output=[{"url": "u"}]))
        yield ModelEvent.server_tool_started(ServerToolCall(id="s2", name="web_fetch", input={"url": "x"}))
        yield ModelEvent.server_tool_failed(ServerToolResult(call_id="s2", name="web_fetch", error_code="timeout"))
        reply = AssistantMessage(content="ok", provider="p", model="m", replay_blocks=({"type": "thinking"},))
        yield ModelEvent.completed(ModelResponse(reply))

    _ = [e async for e in ext.on_model_request(_context(), request, call_next)]
    (record,) = ext.calls(SESSION)
    first, second = record["server_tool_calls"]
    assert first["input"] == {"q": "zett"} and first["status"] == "completed" and first["output"] == [{"url": "u"}]
    assert second["status"] == "failed" and second["error_code"] == "timeout" and second["input"] == {"url": "x"}
    message = record["response"]["message"]
    assert message["provider"] == "p" and message["model"] == "m" and message["replay_blocks"] == [{"type": "thinking"}]
    assert record["request"]["tools"][0]["deferred"] is True
    assert record["request"]["server_tools"][0] == {"type": "web_search", "configuration": {"max_uses": 2}}


async def test_error_is_recorded_and_reraised(tmp_path):
    ext = MonitorExtension(tmp_path)
    ext.set_enabled(SESSION, True)
    with pytest.raises(RuntimeError):
        await _call(ext, fail=True)
    (record,) = ext.calls(SESSION)
    assert record["response"] is None and "boom" in record["error"]


def test_report_is_self_contained_and_escapes(tmp_path):
    ext = MonitorExtension(tmp_path)
    page = render_report(SESSION, [{"number": 1, "text": "</script><b>"}])
    assert "</script><b>" not in page
    assert "\\u003c/script>" in page
    data = page.split('id="data">')[1].split("</script>")[0]
    assert json.loads(data)["calls"][0]["number"] == 1
    assert ext  # keeps the fixture used


def test_the_command_takes_no_subcommands(tmp_path):
    from zettcode.app.plugins.loader import terminal_context
    from zettcode.config import ModelConfig, ZettCodeConfig

    ctx = terminal_context(ZettCodeConfig(workspace=tmp_path, models=(ModelConfig(model="m", token="t"),)))
    MonitorPlugin(tmp_path / "mon").activate(ctx)
    (command,) = ctx.tui.registered_commands
    assert command.name == "/monitor" and not command.subcommands


def _runs_this_checkouts_zettcode() -> bool:
    """Return whether the zettcode imported here is the checkout this plugin is developed beside."""
    import zettcode

    source = Path(__file__).resolve().parents[3] / "zettcode" / "src"
    return Path(zettcode.__file__).resolve().is_relative_to(source)


def test_the_dependency_ranges_take_the_running_zettcode_and_zett_agent():
    """The plugin installs beside zettcode, so its ranges have to admit the release it runs on here.

    The cap was ``<0.2`` once, and a 0.2.x worktree could not install the plugin: pip either refused the local
    checkout or quietly downgraded zettcode to 0.1.x with it. A range that stops short now fails in this test instead.

    ``main`` is the next line before its release commit writes the version, so a checkout of this repository runs a
    zettcode whose version string is one minor below the plugin's floor while the API it needs is already here: the
    import of this module is what proves that. When the zettcode under test is this checkout, the floor is checked
    against the line after it — the release the plugin names — and a floor that skips further ahead still fails. A
    zettcode installed from PyPI has to satisfy the range outright.
    """
    from importlib.metadata import version as installed

    from packaging.requirements import Requirement
    from packaging.version import Version

    project = Path(__file__).resolve().parent.parent / "pyproject.toml"
    declared = (
        line
        for line in re.findall(r'^\s{2}"([^"]+)"', project.read_text(encoding="utf-8"), re.MULTILINE)
        if ">=" in line
    )
    ranges = {requirement.name: requirement for requirement in map(Requirement, declared)}
    assert set(ranges) == {"zettcode", "zett-agent"}, "the runtime dependencies declared in pyproject.toml"
    checkout = _runs_this_checkouts_zettcode()
    for name, requirement in ranges.items():
        current = Version(installed(name))
        if requirement.specifier.contains(current, prereleases=True):
            continue
        floors = [Version(spec.version) for spec in requirement.specifier if spec.operator == ">="]
        assert name == "zettcode" and checkout and len(floors) == 1, (
            f"{requirement} excludes {name} {current}, the release this test runs on"
        )
        floor = floors[0]
        assert (floor.major, floor.minor) == (current.major, current.minor + 1), (
            f"{requirement} excludes {name} {current} and does not name the next line either"
        )


def test_images_are_a_marker_unless_the_reader_keeps_them(tmp_path):
    from zett_agent.messages import ImageBytesSource, ImageContent, TextContent

    from zettcode_monitor.recorder import encode_message

    message = UserMessage(
        content=[TextContent(text="look"), ImageContent(ImageBytesSource(data=b"\x89PNG", media_type="image/png"))]
    )
    assert "images" not in encode_message(message)
    kept = encode_message(message, images=True)
    assert kept["text"] == "look\n[image]" and kept["images"][0].startswith("data:image/png;base64,")
    ext = MonitorExtension(tmp_path)
    assert ext.images(SESSION) is False
    ext.set_images(SESSION, True)
    assert MonitorExtension(tmp_path).images(SESSION) is True and not MonitorExtension(tmp_path).enabled(SESSION)
    ext.set_enabled(SESSION, True)
    assert MonitorExtension(tmp_path).images(SESSION) is True, "the switches are stored side by side"


async def test_command(tmp_path):
    plugin = MonitorPlugin(tmp_path / "mon")
    workspace = tmp_path / "ws"
    workspace.mkdir()
    closed = []
    host = SimpleNamespace(
        agent=SimpleNamespace(session_id=SESSION, workspace=workspace), close_page=lambda: closed.append(1)
    )

    def ctx(arg: str) -> CommandContext:
        return CommandContext(argument=arg, ui=None, host=host)  # type: ignore[arg-type]

    assert (await plugin.monitor(ctx(""))).widget is not None, "the command opens the panel"
    assert (await plugin.monitor(ctx("anything"))).widget is not None, "and ignores what follows it"
    with pytest.raises(ValueError, match="Nothing recorded"):
        plugin.export(SESSION, workspace)
    plugin.extension.set_enabled(SESSION, True)
    await _call(plugin.extension)
    count, written = plugin.export(SESSION, workspace)
    assert count == 1 and written == (workspace / f"zettcode-monitor-{SESSION[:8]}.html").resolve()
    assert written.is_file()


def _page(**over):
    from zettcode.tui.testing import Harness

    from zettcode_monitor.panel import MonitorPage

    log: dict = {"applied": [], "closed": 0, "done": [], "exports": 0}

    def export() -> str:
        log["exports"] += 1
        if over.get("fail"):
            raise ValueError("Nothing recorded yet.")
        return "Exported 2 calls to /x.html"

    page = MonitorPage(
        recording=over.get("recording", False),
        images=False,
        count=lambda: 2,
        on_apply=lambda recording, images: log["applied"].append((recording, images)),
        on_export=export,
        on_close=lambda: log.__setitem__("closed", log["closed"] + 1),
        on_done=lambda said, exported: log["done"].append((said, exported)),
    )
    return page, Harness(page, width=100, height=10), log


def test_panel_moves_switches_but_applies_only_on_enter():
    page, harness, log = _page()
    text = harness.render().text
    assert "Monitor" in text and "off \u00b7 2 calls" in text and "Recording" in text and "Export" in text
    harness.press("right")
    harness.press("down")
    harness.press(" ")
    assert page.recording and page.images and page.changed
    assert log["applied"] == [] and log["closed"] == 0, "nothing happens until enter"
    assert "(not applied)" in harness.render().text
    harness.press("enter")
    assert log["applied"] == [(True, True)] and log["closed"] == 1
    assert log["done"] == [("monitor: recording on, images on", False)]
    assert log["exports"] == 0, "enter on a switch row does not export"


def test_enter_on_a_switch_row_with_nothing_changed_just_closes():
    _, harness, log = _page()
    harness.press("enter")
    assert log["applied"] == [] and log["closed"] == 1


def test_escape_closes_and_discards_the_switches():
    page, harness, log = _page()
    harness.press("right")
    harness.press("escape")
    assert log["applied"] == [] and log["closed"] == 1 and log["done"] == []


def test_enter_on_export_exports_applies_and_closes():
    _, harness, log = _page()
    harness.press("right")
    harness.press("up")  # the marker wraps round to Export
    assert "enter export and close" in harness.render().text
    harness.press("enter")
    assert log["exports"] == 1 and log["closed"] == 1
    assert log["done"] == [("Exported 2 calls to /x.html", True)]
    assert log["applied"] == [(True, False)], "a switch moved before exporting is not thrown away"


def test_a_failed_export_keeps_the_panel_open_and_says_why():
    page, harness, log = _page(fail=True)
    harness.press("up")
    harness.press("enter")
    assert log["closed"] == 0 and log["done"] == [] and "Nothing recorded yet." in harness.render().text
    harness.press("down")
    assert page.error == "", "moving the marker clears the message"
