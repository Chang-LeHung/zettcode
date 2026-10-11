"""The context report: what a request spends its window on, and how it counts."""

from __future__ import annotations

import asyncio
import os
import sys
import time

import pytest
from zett_agent.agent import AgentRunConfig
from zett_agent.extensions.compaction import CompactedMessage
from zett_agent.messages import AssistantMessage, SystemMessage, ToolCall, ToolMessage, UserMessage
from zett_agent.model import ModelRequest, ToolDefinition

from zettcode.app.agent.context import (
    ContextExtension,
    Tokenizer,
    _tiktoken_encoder,
    measure,
    message_text,
    tool_text,
)
from zettcode.paths import DEFAULT_TOKENIZER_CACHE


class _Context:
    """Stand-in for the runtime context: the report only needs the session id."""

    def __init__(self, session_id: str = "s-1") -> None:
        self.config = AgentRunConfig(session_id=session_id)


def _request(messages, tools=()) -> ModelRequest:
    """Build the provider-neutral request the runtime would assemble."""
    return ModelRequest(messages=messages, tools=tools)


def _never_loads(_encoding: str):
    """Refuse to build an encoder: the tokenizer stays on the estimate."""
    raise OSError("no vocabulary, no network")


def _counting_tokenizer(per_token: int = 4) -> Tokenizer:
    """Return a tokenizer whose encoder counts one token per N characters."""

    def loader(_encoding: str):
        return lambda text: list(range(len(text) // per_token))

    return Tokenizer(loader=loader)


def test_the_estimator_counts_characters_when_no_encoder_loaded():
    tokenizer = Tokenizer(deadline=0.0)  # never resolves, so the estimate stands

    assert tokenizer.prepared is False
    assert tokenizer.label.endswith("chars/token")
    assert tokenizer.count("") == 0
    assert tokenizer.count("12345678") == 2


async def test_preparing_loads_the_encoder_and_names_it():
    tokenizer = _counting_tokenizer()

    await tokenizer.prepare()

    assert tokenizer.prepared is True
    assert tokenizer.label == f"tiktoken {tokenizer.encoding}"
    assert tokenizer.count("12345678") == 2


async def test_a_tokenizer_that_cannot_load_stays_on_the_estimate():
    def loader(_encoding: str):
        raise OSError("no vocabulary, no network")

    tokenizer = Tokenizer(loader=loader)
    await tokenizer.prepare()

    assert tokenizer.prepared is False
    assert tokenizer.count("12345678") == 2


async def test_measuring_groups_every_source_of_one_request():
    messages = (
        SystemMessage(content="You are ZettCode."),
        SystemMessage(content="# Filesystem environment"),
        UserMessage(content="add a flag"),
        AssistantMessage(
            content="done",
            reasoning="thinking",
            tool_calls=(ToolCall(id="1", name="read", arguments={"path": "a.py"}),),
        ),
        ToolMessage(tool_call_id="1", name="read", content="file body"),
        CompactedMessage(content="summary of earlier turns"),
    )
    tools = (ToolDefinition(name="read", description="read a file", parameters={"type": "object"}),)

    tokenizer = _counting_tokenizer()
    await tokenizer.prepare()
    report = measure(messages, tools, window=1_000, tokenizer=tokenizer)

    shares = {share.name: (share.tokens, share.items) for share in report.shares}
    assert shares["System prompt"][1] == 1
    assert shares["Environment notes"][1] == 1
    assert shares["Tool schemas"] == (len(tool_text(tools[0])) // 4, 1)
    assert shares["User messages"] == (len("add a flag") // 4, 1)
    assert shares["Assistant messages"][1] == 1
    assert shares["Tool output"] == (len("file body") // 4, 1)
    assert shares["Compaction summary"][1] == 1
    assert report.used == sum(share.tokens for share in report.shares)
    assert report.free == 1_000 - report.used
    assert report.percent(report.used) == pytest.approx(report.used / 10)


async def test_the_providers_total_carries_the_shares_the_tokenizer_measured():
    """One request, two sources: the provider says how many, the counter says where.

    A provider counts what it bills and never breaks a request down by source; a
    tokenizer breaks it down but does not know how the provider counts. So the
    total is the provider's and the rows are measured — and they still add up to
    a hundred, because the shares divide by what the tokenizer counted.
    """
    extension = ContextExtension()
    await extension.before_model(_Context("s-1"), _request((UserMessage(content="a question " * 20),)))
    tokenizer = _counting_tokenizer()

    without = extension.report("s-1", window=1_000_000, tokenizer=tokenizer)
    reported = extension.report("s-1", window=1_000_000, tokenizer=tokenizer, reported=599_165)

    assert without.from_provider is False and without.used == without.measured
    assert reported.from_provider is True
    assert reported.used == 599_165, "the provider's count is the request's size"
    assert reported.measured == without.measured, "and the shares are still measured"
    assert reported.share(sum(share.tokens for share in reported.shares)) == pytest.approx(100.0)
    assert reported.free == 1_000_000 - 599_165, "what is left is measured against the provider's total"


def test_a_full_window_never_reports_negative_room():
    report = measure(
        (UserMessage(content="x" * 4_000),),
        (),
        window=100,
        tokenizer=_counting_tokenizer(),
    )

    assert report.used > report.window
    assert report.free == 0


def test_a_request_without_tools_is_reported_as_partial():
    """A restored session measured before its next reply has no tool schemas yet."""
    without = measure((UserMessage(content="hi"),), (), window=100, tokenizer=_counting_tokenizer())
    with_tools = measure(
        (UserMessage(content="hi"),),
        (ToolDefinition(name="read", description="read a file", parameters={}),),
        window=100,
        tokenizer=_counting_tokenizer(),
    )

    assert without.partial is True
    assert with_tools.partial is False


class _CountingEncoder:
    """An encoder that records what it was asked to count."""

    def __init__(self) -> None:
        """Start with nothing counted."""
        self.texts: list[str] = []

    def encode(self, text: str) -> list[int]:
        """Count one text, remembering it was counted."""
        self.texts.append(text)
        return list(range(len(text) // 4))


async def test_a_report_counts_each_item_once_and_reuses_them_afterwards():
    """`/context` measures what arrived since the last time it was opened.

    Counting is the whole cost of a report, and a turn appends to the context
    rather than rewriting it: what was counted before has not changed. This is
    the difference between a panel that costs 25 ms on a long session every time
    and one that costs what the last turn added.
    """
    encoder = _CountingEncoder()
    tokenizer = Tokenizer(loader=lambda _name: encoder.encode)
    await tokenizer.prepare()
    extension = ContextExtension()
    messages = [SystemMessage(content="You are ZettCode. " * 20)] + [
        UserMessage(content=f"question {index} " * 4) for index in range(5)
    ]
    extension.remember("s-1", messages)

    first = extension.report("s-1", window=100_000, tokenizer=tokenizer)
    counted_first = len(encoder.texts)
    encoder.texts.clear()
    second = extension.report("s-1", window=100_000, tokenizer=tokenizer)

    assert counted_first == len(messages), "the first report counts everything"
    assert encoder.texts == [], "nothing had changed, so nothing is counted again"
    assert second == first

    extension.remember("s-1", [*messages, UserMessage(content="and one more?")])
    encoder.texts.clear()
    third = extension.report("s-1", window=100_000, tokenizer=tokenizer)

    assert len(encoder.texts) == 1, "only the message that arrived is counted"
    assert third.used > first.used


async def test_a_count_belongs_to_the_counter_that_produced_it():
    """The estimate and the encoder disagree by design, so they never mix."""
    plain = Tokenizer(deadline=0.0, loader=_never_loads)
    encoder = _CountingEncoder()
    loaded = Tokenizer(loader=lambda _name: encoder.encode)
    await loaded.prepare()
    extension = ContextExtension()
    extension.remember("s-1", (UserMessage(content="a question " * 20),))

    estimated = extension.report("s-1", window=100_000, tokenizer=plain)
    encoder.texts.clear()
    counted = extension.report("s-1", window=100_000, tokenizer=loaded)

    assert estimated.measured_by != counted.measured_by
    assert len(encoder.texts) == 1, "the loaded counter redoes the work rather than trusting the estimate"


async def test_a_count_is_never_reused_for_a_different_message():
    """The key is identity: another message with the same words is counted again.

    Reusing by text would make the report wrong the moment two messages differ
    in something the text does not show, and the report is a measurement: it may
    be slow, but it may not be a guess.
    """
    counted: list[str] = []

    def encoder(text: str) -> list[int]:
        counted.append(text)
        return list(range(len(text) // 4))

    tokenizer = Tokenizer(loader=lambda _name: encoder)
    await tokenizer.prepare()
    extension = ContextExtension()
    extension.remember("s-1", (UserMessage(content="the same words"),))
    extension.report("s-1", window=1_000, tokenizer=tokenizer)
    counted.clear()

    extension.remember("s-1", (UserMessage(content="the same words"),))
    extension.report("s-1", window=1_000, tokenizer=tokenizer)

    assert counted == ["the same words"], "a different message is counted on its own"


def test_the_encoder_keeps_its_vocabulary_where_the_os_will_not_clean_it(monkeypatch):
    """tiktoken's own cache is the temp directory, which is why this exists.

    A purge there turns the next count into a 1.7 MB download — five seconds,
    measured — behind the deadline below, so the panel would wait and then show
    the estimate. The vocabulary belongs under this program's directory.
    """
    monkeypatch.delenv("TIKTOKEN_CACHE_DIR", raising=False)
    asked: list[str] = []

    class FakeTiktoken:
        @staticmethod
        def get_encoding(name: str):
            asked.append(name)
            return type("Encoder", (), {"encode": lambda self, text: [0] * len(text)})()

    monkeypatch.setitem(sys.modules, "tiktoken", FakeTiktoken)

    encoder = _tiktoken_encoder("cl100k_base")

    assert asked == ["cl100k_base"]
    assert os.environ["TIKTOKEN_CACHE_DIR"] == str(DEFAULT_TOKENIZER_CACHE)
    assert encoder("abcd") == [0, 0, 0, 0]


def test_an_explicit_cache_directory_wins(monkeypatch, tmp_path):
    """The reader's own choice of cache directory is not ours to overwrite."""
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(tmp_path / "yours"))

    class FakeTiktoken:
        @staticmethod
        def get_encoding(name: str):
            return type("Encoder", (), {"encode": lambda self, text: [0]})()

    monkeypatch.setitem(sys.modules, "tiktoken", FakeTiktoken)

    _tiktoken_encoder("cl100k_base")

    assert os.environ["TIKTOKEN_CACHE_DIR"] == str(tmp_path / "yours")


async def test_a_load_that_missed_its_deadline_is_adopted_when_it_arrives():
    """The wait is over, but the answer is not thrown away with it."""
    slow = Tokenizer(deadline=0.01, loader=lambda _name: (time.sleep(0.3), lambda text: [0] * len(text))[1])
    await slow.prepare()

    assert slow.prepared is False, "the deadline is what keeps a panel from waiting"

    deadline = time.perf_counter() + 5.0
    while not slow.prepared and time.perf_counter() < deadline:
        await slow.prepare()
        await asyncio.sleep(0.02)

    assert slow.prepared is True, "a later report should not estimate for the rest of the session"
    assert slow.label.startswith("tiktoken")


async def test_priming_a_restored_session_makes_it_measurable():
    extension = ContextExtension()
    extension.remember("restored", (UserMessage(content="an earlier question"),))

    report = extension.report("restored", window=1_000, tokenizer=_counting_tokenizer())

    assert report is not None
    assert [share.name for share in report.shares] == ["User messages"]
    assert report.partial is True  # no request ran yet, so the tools are unknown


def test_message_text_covers_content_reasoning_and_tool_calls():
    assistant = AssistantMessage(
        content="answer", reasoning="why", tool_calls=(ToolCall(id="1", name="grep", arguments={"q": "x"}),)
    )

    text = message_text(assistant)

    assert "answer" in text and "why" in text and "grep" in text and '"q"' in text
    assert message_text(ToolMessage(tool_call_id="1", name="read", content="body")) == "body"
    assert message_text(SystemMessage(content="instructions")) == "instructions"


async def test_the_extension_remembers_the_last_request_per_session():
    extension = ContextExtension()
    first = _request((SystemMessage(content="one"),))
    second = _request((SystemMessage(content="two"), SystemMessage(content="notes")))

    assert extension.assembled("s-1") is None

    await extension.before_model(_Context("s-1"), first)
    await extension.before_model(_Context("s-1"), second)
    await extension.before_model(_Context("s-2"), first)

    assert extension.assembled("s-1") == (second.messages, second.tools)
    assert extension.report("s-2", window=100, tokenizer=_counting_tokenizer()) is not None
    assert extension.report("missing", window=100, tokenizer=_counting_tokenizer()) is None
