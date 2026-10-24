"""Compaction counts the context without loading a vocabulary on the event loop."""

from __future__ import annotations

import asyncio
import sys
import threading
import time

import pytest
from zett_agent.extensions.compaction import CompactionExtension
from zett_agent.messages import (
    AssistantMessage,
    ImageContent,
    ImageUrlSource,
    SystemMessage,
    TextContent,
    ToolMessage,
    UserMessage,
)

from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.engine import core as runtime_module
from zettcode.engine.extensions import context as context_module
from zettcode.engine.extensions.compaction import (
    COMPACTION_ENCODING,
    COUNTER_WAIT,
    CompactionCounter,
    OnDemandCompaction,
)


def _messages(text: str = "x" * 400):
    return [SystemMessage(content="rules"), UserMessage(content=text), AssistantMessage(content=text)]


def _encoder(text: str) -> list[int]:
    return [0] * len(text)


class _Gate:
    """A loader that finishes when it is told to, and remembers which thread it ran on."""

    def __init__(self, *, fail: bool = False) -> None:
        self.release = threading.Event()
        self.threads: list[int] = []
        self.calls: list[str] = []
        self.fail = fail

    def __call__(self, encoding: str):
        self.threads.append(threading.get_ident())
        self.calls.append(encoding)
        self.release.wait(10)
        if self.fail:
            raise OSError("no network")
        return _encoder


@pytest.fixture
def exact(monkeypatch):
    """Replace zett-agent's exact counter, so the delegation can be seen without a real vocabulary."""
    seen: list[object] = []

    def counted(messages):
        seen.append(messages)
        return 12345

    monkeypatch.setattr(CompactionExtension, "_count_tokens", staticmethod(counted))
    return seen


# -- what is warmed is what zett-agent asks for -------------------------------------------------------


def test_the_encoding_that_is_warmed_is_the_one_zett_agents_counter_asks_tiktoken_for(monkeypatch):
    """Warming another one — the report's `cl100k_base` was warmed all along — leaves this one to load
    on the loop at the first turn, which is the stall this module exists to remove."""
    asked: list[str] = []

    class FakeTiktoken:
        @staticmethod
        def get_encoding(name: str):
            asked.append(name)
            return type("Encoder", (), {"encode_ordinary": lambda self, text: [0] * len(text)})()

    monkeypatch.setitem(sys.modules, "tiktoken", FakeTiktoken)

    CompactionExtension._count_tokens([UserMessage(content="hello")])

    assert asked and set(asked) == {COMPACTION_ENCODING}


def test_the_default_encoding_is_not_the_reports():
    assert COMPACTION_ENCODING == "o200k_base" != context_module.Tokenizer().encoding


# -- before the encoding is loaded ---------------------------------------------------------------------


async def test_before_the_load_finishes_a_count_is_an_estimate_and_nothing_is_loaded_by_the_caller(exact):
    gate = _Gate()
    counter = CompactionCounter(loader=gate)
    counter.start()
    await asyncio.sleep(0.05)
    assert gate.calls == [COMPACTION_ENCODING] and not counter.ready

    started = time.perf_counter()
    tokens = counter.count(_messages("y" * 4000))
    elapsed = time.perf_counter() - started

    assert exact == [], "zett-agent's counter, which would load the vocabulary here, was not called"
    assert tokens == 1 + 1000 + 1000, "five characters of rules, then two messages of four thousand"
    assert elapsed < 0.05
    gate.release.set()


async def test_the_load_runs_on_a_thread_of_its_own_not_the_callers():
    gate = _Gate()
    counter = CompactionCounter(loader=gate)
    counter.start()
    await asyncio.sleep(0.05)

    assert gate.threads and gate.threads[0] != threading.get_ident()
    gate.release.set()


async def test_starting_returns_at_once_whatever_the_load_costs():
    gate = _Gate()
    counter = CompactionCounter(loader=gate)

    started = time.perf_counter()
    counter.start()
    elapsed = time.perf_counter() - started

    assert elapsed < 0.05, "start does not wait for the load"
    gate.release.set()


def test_a_counter_that_was_never_started_estimates_and_is_not_ready(exact):
    counter = CompactionCounter(loader=_Gate())

    assert counter.ready is False
    assert counter.count(_messages()) > 0 and exact == []


@pytest.mark.parametrize(
    ("text", "tokens"),
    [("", 1), ("a", 1), ("x" * 4, 1), ("x" * 40, 10), ("x" * 4000, 1000)],
)
def test_an_estimate_is_the_length_over_the_usual_characters_per_token_and_never_less_than_one(text, tokens):
    assert CompactionCounter._estimate(UserMessage(content=text)) == tokens


def test_an_estimate_charges_what_zett_agent_charges_for_a_picture():
    picture = ImageContent(source=ImageUrlSource(url="data:image/png;base64," + "A" * 300_000))
    message = UserMessage(content=[TextContent(text="look at this"), picture, picture])

    estimate = CompactionCounter._estimate(message)

    # The charge is the framework's; the text around it is what is left of the message once each
    # picture is replaced by a short marker (a few tokens apiece, so an estimate leans high).
    assert 2 * 1_100 <= estimate < 2 * 1_100 + 20, f"{estimate} tokens: the pictures' bytes were read as text"


def test_an_estimate_reads_every_kind_of_message():
    for message in (
        SystemMessage(content="s" * 40),
        UserMessage(content="u" * 40),
        AssistantMessage(content="a" * 40),
        ToolMessage(tool_call_id="c", name="read_file", content="t" * 40),
    ):
        assert CompactionCounter._estimate(message) >= 10


# -- once it is loaded ---------------------------------------------------------------------------------


async def test_once_loaded_the_count_is_zett_agents_own_so_the_threshold_is_decided_as_before(exact):
    gate = _Gate()
    counter = CompactionCounter(loader=gate)
    counter.start()
    gate.release.set()

    assert await counter.wait(2.0) is True

    messages = _messages()
    assert counter.ready is True and counter.count(messages) == 12345
    assert exact == [messages]


async def test_a_load_that_finishes_after_the_wait_is_adopted_by_the_next_count(exact):
    gate = _Gate()
    counter = CompactionCounter(loader=gate)
    counter.start()
    assert await counter.wait(0.05) is False
    assert counter.count(_messages()) != 12345, "still an estimate"

    gate.release.set()
    deadline = time.perf_counter() + 5
    while not counter.ready and time.perf_counter() < deadline:
        await asyncio.sleep(0.01)

    assert counter.count(_messages()) == 12345, "and exact from the moment it arrived"


# -- the wait --------------------------------------------------------------------------------------------


async def test_the_wait_is_bounded_so_a_first_run_with_no_network_does_not_wait_for_a_download():
    gate = _Gate()
    counter = CompactionCounter(loader=gate)
    counter.start()

    started = time.perf_counter()
    ready = await counter.wait(0.1)
    elapsed = time.perf_counter() - started

    assert ready is False and 0.08 < elapsed < 1.0
    gate.release.set()


async def test_the_wait_leaves_the_event_loop_free():
    """The point of waiting here rather than there: the interface keeps painting and reading keys."""
    gate = _Gate()
    counter = CompactionCounter(loader=gate)
    counter.start()
    beats: list[float] = []

    async def heartbeat():
        while True:
            beats.append(time.perf_counter())
            await asyncio.sleep(0.005)

    beating = asyncio.ensure_future(heartbeat())
    await counter.wait(0.3)
    beating.cancel()

    gaps = [b - a for a, b in zip(beats, beats[1:], strict=False)]
    assert len(beats) > 20, "the loop kept turning"
    assert max(gaps) < 0.1, f"the loop stalled for {max(gaps) * 1000:.0f} ms"
    gate.release.set()


async def test_the_wait_returns_as_soon_as_the_load_is_done_not_at_the_deadline():
    gate = _Gate()
    counter = CompactionCounter(loader=gate)
    counter.start()
    asyncio.get_running_loop().call_later(0.05, gate.release.set)

    started = time.perf_counter()
    ready = await counter.wait(5.0)

    assert ready is True and time.perf_counter() - started < 1.0


async def test_waiting_on_a_counter_that_was_never_started_is_not_an_error():
    assert await CompactionCounter(loader=_Gate()).wait(0.01) is False


def test_the_wait_the_first_turn_allows_is_short_enough_to_be_a_pause_and_not_a_hang():
    assert 0 < COUNTER_WAIT <= 5


# -- a load that fails ------------------------------------------------------------------------------------


async def test_a_load_that_fails_leaves_an_estimate_for_good_and_raises_nothing(exact):
    gate = _Gate(fail=True)
    counter = CompactionCounter(loader=gate)
    counter.start()
    gate.release.set()

    assert await counter.wait(2.0) is False

    assert counter.ready is False
    assert counter.count(_messages()) > 0 and exact == []


# -- the extension and the runtime use it -------------------------------------------------------------------


def test_the_extension_counts_through_the_counter_it_is_given():
    seen: list[object] = []

    def mine(messages):
        seen.append(messages)
        return 7

    extension = OnDemandCompaction(None, max_tokens=1000, keep_recent_tokens=100, count_tokens=mine)

    assert extension.count_tokens(_messages()) == 7 and len(seen) == 1


def _preview(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_module.os, "chdir", lambda path: None)
    config = ZettCodeConfig(
        workspace=tmp_path,
        models=(ModelConfig(model="m", token="t"),),
        store=tmp_path / "sessions",
        mcp_config=tmp_path / "absent-mcp.json",
    )
    return runtime_module.ZettCodeEngine.preview(config)


def test_the_runtimes_compaction_counts_through_the_runtimes_counter(tmp_path, monkeypatch):
    runtime = _preview(tmp_path, monkeypatch)

    assert runtime.compaction.count_tokens == runtime.compaction_counter.count
    assert runtime.compaction_counter.encoding == COMPACTION_ENCODING


async def test_starting_the_runtime_starts_the_load_and_the_build_waits_for_it(tmp_path, monkeypatch):
    runtime = _preview(tmp_path, monkeypatch)
    events: list[str] = []

    class SpyCounter(CompactionCounter):
        def start(self):
            events.append("start")
            super().start()

        async def wait(self, timeout=COUNTER_WAIT):
            events.append("wait")
            return await super().wait(timeout)

    gate = _Gate()
    gate.release.set()
    runtime.compaction_counter = SpyCounter(loader=gate)

    async def fake_create_agent(model, **kwargs):
        events.append("create_agent")
        return type("FakeClient", (), {"event_dispatcher": None})()

    monkeypatch.setattr("zett_agent.client.create_agent", fake_create_agent)

    await runtime.start()

    assert events == ["start", "wait", "create_agent"], "loaded on its own thread, awaited, and only then the client"
    assert gate.threads and gate.threads[0] != threading.get_ident()


async def test_a_counter_that_never_loads_does_not_hold_the_first_turn_for_longer_than_its_wait(tmp_path, monkeypatch):
    runtime = _preview(tmp_path, monkeypatch)
    gate = _Gate()
    runtime.compaction_counter = CompactionCounter(loader=gate)
    monkeypatch.setattr(runtime_module, "COUNTER_WAIT", 0.2)

    async def fake_create_agent(model, **kwargs):
        return type("FakeClient", (), {"event_dispatcher": None})()

    monkeypatch.setattr("zett_agent.client.create_agent", fake_create_agent)
    started = time.perf_counter()
    await runtime.start()
    elapsed = time.perf_counter() - started

    assert 0.15 < elapsed < 2.0, f"the build waited for the counter's wait and no longer ({elapsed:.2f}s)"
    assert runtime.client is not None
    gate.release.set()


def test_the_suite_never_reaches_for_a_vocabulary(tmp_path, monkeypatch):
    """conftest makes the default loader answer as if offline; this is what keeps a test from a download."""
    with pytest.raises(OSError, match="not fetched in tests"):
        context_module._tiktoken_encoder("o200k_base")


# -- the SDK's resource tree, which the first request used to import on the loop -----------------------


def test_after_the_warm_up_the_first_request_does_not_import_the_openai_resource_tree():
    """What the name in the warm list is for, checked where it counts: in a fresh interpreter, import the
    modules the runtime warms, then do what the first request does and count what that still imports.
    Without `openai.resources` it is five hundred modules; with it, a few dozen."""
    import subprocess
    import textwrap

    code = textwrap.dedent(
        """
        import sys
        from zettcode.engine.core import OPENAI_WARM_MODULES
        import importlib
        for name in OPENAI_WARM_MODULES:
            importlib.import_module(name)
        import openai
        before = set(sys.modules)
        client = openai.AsyncOpenAI(api_key="x", base_url="http://127.0.0.1:1")
        client.chat.completions
        print(len(set(sys.modules) - before))
        """
    )
    imported = int(subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout)

    assert imported < 150, f"the first request still imports {imported} modules"


async def test_the_counter_loads_through_the_one_entry_point_the_suite_can_turn_off(monkeypatch):
    """Otherwise a test that starts a runtime would fetch a vocabulary, because nothing could stop it."""
    asked: list[str] = []

    def spy(encoding: str):
        asked.append(encoding)
        return _encoder

    monkeypatch.setattr(context_module, "_tiktoken_encoder", spy)
    counter = CompactionCounter()
    counter.start()

    assert await counter.wait(2.0) is True
    assert asked == [COMPACTION_ENCODING]
