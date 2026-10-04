"""The context report: what a request spends its window on, and how it counts."""

from __future__ import annotations

import pytest
from zett_agent import (
    AgentRunConfig,
    AssistantMessage,
    ModelRequest,
    SystemMessage,
    ToolCall,
    ToolDefinition,
    ToolMessage,
    UserMessage,
)
from zett_agent.extensions.compaction import CompactedMessage

from zettcode.app.agent.context import ContextExtension, Tokenizer, measure, message_text, tool_text


class _Context:
    """Stand-in for the runtime context: the report only needs the session id."""

    def __init__(self, session_id: str = "s-1") -> None:
        self.config = AgentRunConfig(session_id=session_id)


def _request(messages, tools=()) -> ModelRequest:
    """Build the provider-neutral request the runtime would assemble."""
    return ModelRequest(messages=messages, tools=tools)


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
