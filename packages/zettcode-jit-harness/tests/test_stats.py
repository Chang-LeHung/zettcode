"""``profile_tools`` reads how tools have done from the stored conversation, and never reads a long one whole."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from zett_agent.jit_harness import JITHarness

from zettcode.engine.extensions.harness_switch import HarnessSwitch
from zettcode.jit_harness import stats
from zettcode.jit_harness.extension import SwitchedHarness
from zettcode.jit_harness.stats import ERRORS_KEPT, MAX_NAMES, MAX_ROWS, Scan, build_report, scan_tool_calls


def result(name: str, *, ok: bool = True, content: str = "done", ms: float | None = 5.0, call: str = "c") -> str:
    """One stored line: the result of a tool call, in the shape the session store writes."""
    timing = {"duration_ns": None if ms is None else int(ms * 1_000_000)}
    part = {"kind": 4, "data": {"name": name, "success": ok, "tool_call_id": call, "content": content}}
    return json.dumps({"kind": "message", "message": [part], "timing": timing})


def write(path: Path, *lines: str, newline: bool = True) -> Path:
    # newline="\n": the window is measured in bytes, and Windows would otherwise write each line break as two.
    path.write_text("\n".join(lines) + ("\n" if newline else ""), encoding="utf-8", newline="\n")
    return path


def test_calls_failures_time_and_size_are_counted_per_tool(tmp_path: Path):
    path = write(
        tmp_path / "data.jsonl",
        result("bash", ms=10, content="x" * 100),
        result("bash", ms=30, content="y" * 300),
        result("bash", ok=False, ms=20, content="exit code 2"),
        result("read_file", ms=1, content="z"),
    )

    scan = scan_tool_calls(path)

    bash = scan.tools["bash"]
    assert (bash.calls, bash.failed, bash.completed) == (3, 1, 2)
    assert bash.total_ms / bash.timed == 20
    assert bash.total_chars == 100 + 300 + len("exit code 2")
    assert scan.tools["read_file"].calls == 1
    assert not scan.partial and scan.describe() == "the whole of this session"


def test_what_is_not_a_tool_result_is_ignored(tmp_path: Path):
    user_text = json.dumps(
        {"kind": "message", "message": [{"kind": 1, "data": {"content": 'quotes "tool_call_id" in a question'}}]}
    )
    path = write(
        tmp_path / "data.jsonl",
        user_text,
        "not json at all but it says " + '"tool_call_id"',
        json.dumps({"kind": "compaction", "message": "x", "tool_call_id": 1}),
        json.dumps({"kind": "message", "message": [{"data": {"tool_call_id": "c", "name": 3, "success": True}}]}),
        result("bash"),
    )

    scan = scan_tool_calls(path)

    assert {name: tally.calls for name, tally in scan.tools.items()} == {"bash": 1}


def test_a_call_with_no_recorded_time_still_counts_but_does_not_skew_the_average(tmp_path: Path):
    path = write(tmp_path / "data.jsonl", result("bash", ms=None), result("bash", ms=40))

    tally = scan_tool_calls(path).tools["bash"]

    assert tally.calls == 2 and tally.timed == 1 and tally.total_ms == 40


def test_recent_errors_are_distinct_newest_last_and_bounded(tmp_path: Path):
    lines = [result("bash", ok=False, content=f"error {n}") for n in range(ERRORS_KEPT + 3)]
    lines.append(result("bash", ok=False, content="error 5"))  # seen again: it is the newest now
    tally = scan_tool_calls(write(tmp_path / "data.jsonl", *lines)).tools["bash"]

    assert len(tally.errors) == ERRORS_KEPT
    assert tally.errors[-1] == "error 5"
    assert tally.errors.count("error 5") == 1
    assert "error 0" not in tally.errors, "the oldest are the ones that go"


def test_an_error_message_is_kept_short_and_on_one_line(tmp_path: Path):
    path = write(tmp_path / "data.jsonl", result("bash", ok=False, content="line one\n\n  line   two " + "x" * 1000))

    (message,) = scan_tool_calls(path).tools["bash"].errors

    assert message.startswith("line one line two ") and len(message) <= stats.ERROR_CHARS


def test_only_the_tail_is_read_and_the_line_the_window_opens_inside_is_dropped(tmp_path: Path):
    old = [result("old_tool", call=f"o{n}") for n in range(50)]
    new = [result("new_tool", call=f"n{n}") for n in range(5)]
    path = write(tmp_path / "data.jsonl", *old, *new)
    window = sum(len(line) + 1 for line in new) + 10  # the five new lines and a piece of the last old one

    scan = scan_tool_calls(path, max_bytes=window)

    assert "old_tool" not in scan.tools, "the piece of a line is not parsed"
    assert scan.tools["new_tool"].calls == 5
    assert scan.partial and scan.scanned < scan.size
    assert "older calls are not counted" in scan.describe()


def test_a_window_that_opens_exactly_at_a_line_keeps_that_line(tmp_path: Path):
    lines = [result("a", call="1"), result("b", call="2"), result("c", call="3")]
    path = write(tmp_path / "data.jsonl", *lines)
    window = len(lines[1]) + 1 + len(lines[2]) + 1

    scan = scan_tool_calls(path, max_bytes=window)

    assert set(scan.tools) == {"b", "c"}


def test_a_last_line_with_no_newline_is_counted(tmp_path: Path):
    path = write(tmp_path / "data.jsonl", result("bash"), result("bash"), newline=False)

    assert scan_tool_calls(path).tools["bash"].calls == 2


def test_a_line_of_exactly_the_limit_is_read_and_one_byte_more_is_not(tmp_path: Path):
    limit = 2_000
    fits = result("fits", content="x" * (limit - len(result("fits", content=""))))
    over = result("over", content="x" * (limit + 1 - len(result("over", content=""))))
    assert len(fits.encode()) == limit and len(over.encode()) == limit + 1
    path = write(tmp_path / "data.jsonl", fits, over, result("after"))

    scan = scan_tool_calls(path, max_line=limit)

    assert set(scan.tools) == {"fits", "after"}
    assert scan.skipped == 1


@pytest.mark.parametrize("size", [3_000, 40_000])
def test_a_line_that_is_too_long_is_skipped_unparsed_and_the_next_line_is_still_read(tmp_path: Path, monkeypatch, size):
    monkeypatch.setattr(stats, "_DRAIN", 1024)  # so the oversized line is thrown away in several pieces
    path = write(
        tmp_path / "data.jsonl",
        result("before"),
        result("huge", content="h" * size),
        result("after"),
    )

    scan = scan_tool_calls(path, max_line=2_000)

    assert set(scan.tools) == {"before", "after"}
    assert scan.skipped == 1
    assert "1 results too large to read" in scan.describe()


def test_an_oversized_line_cut_by_the_window_start_does_not_swallow_the_next_one(tmp_path: Path):
    path = write(tmp_path / "data.jsonl", result("huge", content="h" * 5_000), result("after"), result("last"))

    scan = scan_tool_calls(path, max_bytes=len(result("after")) + len(result("last")) + 100, max_line=2_000)

    assert set(scan.tools) == {"after", "last"}


def test_memory_stays_flat_however_many_calls_the_file_holds(tmp_path: Path):
    path = write(
        tmp_path / "data.jsonl", *[result("bash", ok=n % 2 == 0, content=f"e{n}", call=str(n)) for n in range(5000)]
    )

    scan = scan_tool_calls(path)

    assert scan.tools["bash"].calls == 5000
    assert len(scan.tools["bash"].errors) == ERRORS_KEPT


def test_a_missing_or_empty_file_is_an_empty_scan_that_says_so(tmp_path: Path):
    missing = scan_tool_calls(tmp_path / "none.jsonl")
    empty = scan_tool_calls(write(tmp_path / "data.jsonl", newline=False))

    for scan in (missing, empty):
        assert scan.tools == {} and not scan.partial
        assert scan.describe() == "this session has no stored conversation yet"


CATALOG = {
    "bash": {"origin": "base", "status": "loaded"},
    "grep": {"origin": "base", "status": "loaded"},
    "twice": {"origin": "python", "status": "loaded"},
}


def scanned(tmp_path: Path, *lines: str) -> Scan:
    return scan_tool_calls(write(tmp_path / "data.jsonl", *lines))


def test_an_overview_lists_the_models_tools_and_the_applications_that_were_called(tmp_path: Path):
    scan = scanned(tmp_path, result("bash", ms=10), result("bash", ok=False, content="boom", ms=30))

    report = build_report(scan, CATALOG, None)

    rows = {row["name"]: row for row in report["tools"]}
    assert set(rows) == {"bash", "twice"}, "grep was never called and is the application's: it is not worth a row"
    assert rows["bash"]["calls"] == 2 and rows["bash"]["success_rate"] == 0.5 and rows["bash"]["avg_ms"] == 20
    assert rows["bash"]["recent_errors"] == ["boom"]
    assert rows["twice"]["calls"] == 0 and rows["twice"]["success_rate"] is None, "unused is an answer"
    assert report["window"] == "the whole of this session" and report["omitted"] == 0


def test_an_overview_puts_the_most_called_first_and_says_what_it_left_out():
    scan = Scan()
    catalog = {}
    for number in range(MAX_ROWS + 4):
        name = f"t{number:02d}"
        catalog[name] = {"origin": "python", "status": "loaded"}
        scan.tools[name] = stats.Tally(calls=number)

    report = build_report(scan, catalog, None)

    assert len(report["tools"]) == MAX_ROWS and report["omitted"] == 4
    assert report["tools"][0]["name"] == f"t{MAX_ROWS + 3:02d}"


def test_a_tool_asked_for_by_name_shows_up_to_three_errors_and_zeros_when_never_called(tmp_path: Path):
    scan = scanned(tmp_path, *[result("bash", ok=False, content=f"e{n}") for n in range(5)])

    report = build_report(scan, CATALOG, ["grep", "bash"])

    assert [row["name"] for row in report["tools"]] == ["grep", "bash"], "in the order asked"
    assert report["tools"][0]["calls"] == 0
    assert report["tools"][1]["recent_errors"] == ["e4", "e3", "e2"]


@pytest.mark.parametrize(
    ("names", "needle"),
    [(["nope"], "Unknown tool: nope"), ([], "Name between"), ([f"t{n}" for n in range(MAX_NAMES + 1)], "Name between")],
)
def test_a_bad_request_for_names_is_refused_in_words(names, needle):
    with pytest.raises(ValueError, match=needle):
        build_report(Scan(), CATALOG, names)


def test_a_control_tool_is_never_measured():
    catalog = {**CATALOG, "repo_load": {"origin": "management", "status": "loaded"}}

    report = build_report(Scan(), catalog, None, management={"repo_load"})

    assert "repo_load" not in {row["name"] for row in report["tools"]}


class _Toolbox:
    """What the tool asks of the framework's harness: the catalog and the control tools' names."""

    management_names = frozenset({"repo_create", "repo_load", "repo_unload", "profile_tools"})

    def list_tools(self):
        return [{"name": name, **entry} for name, entry in CATALOG.items()]


def tool_of(extension: SwitchedHarness, session: str = "s"):
    harness = JITHarness(extension._root / session)
    extension._sessions[session] = harness  # as the framework's on_tool records it before asking for the tools
    return {each.name: each for each in extension.management_tools(harness)}


def test_the_four_control_tools_are_still_offered_and_profile_tools_is_the_one_that_reads_the_file(tmp_path: Path):
    extension = SwitchedHarness(tmp_path / "harness", HarnessSwitch(on=True), session_file=lambda session: None)

    tools = tool_of(extension)

    assert set(tools) == {"repo_create", "repo_load", "repo_unload", "profile_tools"}
    assert "in this session" in tools["profile_tools"].description


async def test_profile_tools_answers_from_the_sessions_own_file(tmp_path: Path):
    files = {
        "a": write(tmp_path / "a.jsonl", result("bash", ms=10)),
        "b": write(tmp_path / "b.jsonl", result("bash", ms=10), result("bash", ms=30), result("grep")),
    }
    extension = SwitchedHarness(tmp_path / "harness", HarnessSwitch(on=True), session_file=files.get)
    profile = extension._usage_tool(_Toolbox(), "b")  # type: ignore[arg-type]
    report = await profile({"names": ["bash"]})

    assert report["tools"][0]["calls"] == 2 and report["tools"][0]["avg_ms"] == 20


async def test_a_session_with_no_stored_conversation_gets_an_honest_empty_answer(tmp_path: Path):
    extension = SwitchedHarness(tmp_path / "harness", HarnessSwitch(on=True), session_file=lambda session: None)
    profile = extension._usage_tool(_Toolbox(), "s")  # type: ignore[arg-type]

    report = await profile({})

    assert report["window"] == "this session has no stored conversation yet"


async def test_a_long_conversation_is_read_off_the_event_loop(tmp_path: Path, monkeypatch):
    seen: list[bool] = []
    original = stats.scan_tool_calls

    def spy(path, **kwargs):
        try:
            asyncio.get_running_loop()
            seen.append(True)  # on the loop's own thread
        except RuntimeError:
            seen.append(False)  # in a worker thread
        return original(path, **kwargs)

    monkeypatch.setattr("zettcode.jit_harness.extension.scan_tool_calls", spy)
    path = write(tmp_path / "data.jsonl", result("bash"))
    extension = SwitchedHarness(tmp_path / "harness", HarnessSwitch(on=True), session_file=lambda session: path)

    await extension._usage_tool(_Toolbox(), "s")({})  # type: ignore[arg-type]

    assert seen == [False]


def test_the_real_store_path_is_what_the_plugin_hands_over(tmp_path: Path):
    from zettcode.engine.storage.store import SessionStore

    store = SessionStore(tmp_path / "sessions", workspace=tmp_path)

    assert store.session_path("abc") == store.session_dir("abc") / "data.jsonl"
    with pytest.raises(ValueError):
        store.session_path("../escape")


def test_the_report_is_plain_data_a_model_can_be_shown():
    report = build_report(SimpleNamespace(tools={}, describe=lambda: "w"), CATALOG, None)  # type: ignore[arg-type]

    assert json.loads(json.dumps(report))["tools"][0]["name"] == "twice"


class _Calls:
    """A model that calls ``profile_tools`` once, then answers, and keeps what the tool handed back."""

    from zett_agent.model import RetryOptions

    retry = RetryOptions(max_retries=0)

    def __init__(self) -> None:
        self.requests: list[object] = []

    async def stream(self, request):
        from zett_agent.messages import AssistantMessage, ToolCall
        from zett_agent.model import ModelEvent, ModelResponse

        self.requests.append(request)
        if len(self.requests) == 1:
            call = ToolCall(id="p1", name="profile_tools", arguments={"names": ["twice"]})
            yield ModelEvent.completed(ModelResponse(AssistantMessage(content="", tool_calls=(call,))))
        else:
            yield ModelEvent.completed(ModelResponse(AssistantMessage(content="ok")))


async def test_a_model_calls_profile_tools_and_is_handed_the_counts_with_the_window(tmp_path: Path):
    """Through a real agent: the report, with its extra ``window`` field, survives the framework's own wrapping."""
    from zett_agent.agent import Agent, AgentRunConfig
    from zett_agent.events import AgentEventType
    from zett_agent.tools.base import AgentTool, ToolExecutionMode, tool

    @tool(execution_mode=ToolExecutionMode.SERIAL)
    async def twice(value: int) -> int:
        """Return twice the value.

        Snippet:
            twice(value=2)

        Guidelines:
            - Use it to double a number.
        """
        return value * 2

    path = write(tmp_path / "data.jsonl", result("twice", ms=4), result("twice", ok=False, content="bad input"))
    model = _Calls()
    extension = SwitchedHarness(tmp_path / "harness", HarnessSwitch(on=True), session_file=lambda session: path)
    agent = await Agent.create(
        model,
        config=AgentRunConfig(session_id="s"),
        tools=[twice],
        extensions=[extension],  # type: ignore[arg-type]
    )

    events = [event async for event in agent.stream("how are my tools doing", config=AgentRunConfig(session_id="s"))]

    assert events[-1].type is AgentEventType.RUN_COMPLETED
    handed_back = [m for m in model.requests[1].messages if getattr(m, "name", "") == "profile_tools"]  # type: ignore[attr-defined]
    assert handed_back and handed_back[0].success is True, handed_back
    report = json.loads(handed_back[0].content)
    assert report["window"] == "the whole of this session"
    assert report["tools"][0]["name"] == "twice" and report["tools"][0]["calls"] == 2
    assert report["tools"][0]["recent_errors"] == ["bad input"]
    assert isinstance(twice, AgentTool)
