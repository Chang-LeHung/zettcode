"""Session titles: the summarizing call and the stored title record."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from zett_agent.messages import AssistantMessage, UserMessage
from zett_agent.model import ModelEvent, ModelRequest, ModelResponse, RetryOptions

from zettcode.app.agent.agent import ZettCodeAgent
from zettcode.app.agent.storage import MAX_TITLE, SessionStore
from zettcode.app.agent.title import MAX_TITLE_CHARS, clean_title, excerpt, summarize_title


class FakeModel:
    """A model that replays one canned reply and records the requests it saw."""

    retry = RetryOptions(max_retries=0)

    def __init__(self, reply: str = "Fix the parser crash") -> None:
        self.reply = reply
        self.requests: list[ModelRequest] = []

    async def stream(self, request: ModelRequest):
        """Yield the reply as a delta, then the terminal response the runtime expects."""
        self.requests.append(request)
        yield ModelEvent.text(self.reply)
        yield ModelEvent.completed(ModelResponse(AssistantMessage(content=self.reply)))


@dataclass
class FakeRuntime:
    """The slice of the runtime the title path touches."""

    persistence: SessionStore
    model: FakeModel


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        ("Fix the parser crash", "Fix the parser crash"),
        ("  1. **Fix the parser crash.**  ", "Fix the parser crash"),
        ('"Fix the parser crash"', "Fix the parser crash"),
        ("```\nFix the parser crash\n```", "Fix the parser crash"),
        ("### Fix the parser crash", "Fix the parser crash"),
        ("Why does the parser crash?", "Why does the parser crash?"),
        ("", None),
        ("...", None),
    ],
)
def test_clean_title_reduces_a_model_reply_to_one_line(reply, expected):
    assert clean_title(reply) == expected


def test_clean_title_caps_the_length():
    title = clean_title("x" * 500)

    assert title is not None
    assert len(title) == MAX_TITLE_CHARS


def test_excerpt_collapses_whitespace_and_bounds_the_length():
    assert excerpt("a\n\nb\tc") == "a b c"
    assert len(excerpt("x" * 5000)) == 1200


async def test_summarize_title_asks_the_model_once_for_a_title():
    model = FakeModel("1) **Name the session**")

    title = await summarize_title(model, question="the parser crashes", answer="I fixed the escaping")

    assert title == "Name the session"
    assert len(model.requests) == 1
    prompt = model.requests[0].messages[-1].text
    assert "the parser crashes" in prompt
    assert "I fixed the escaping" in prompt
    assert model.requests[0].tools == ()


async def test_title_session_names_the_first_exchange_once(tmp_path):
    store = SessionStore(tmp_path)
    await store.append("alpha-1", "req", UserMessage(content="the parser crashes"))
    await store.append("alpha-1", "req", AssistantMessage(content="I fixed the escaping"))
    model = FakeModel("Fix the parser crash")
    agent = ZettCodeAgent(FakeRuntime(store, model))

    assert await agent.title_session("alpha-1") == "Fix the parser crash"
    assert store.session_title("alpha-1") == "Fix the parser crash"
    assert (await store.list_sessions())[0].title == "Fix the parser crash"

    # A named session is never renamed, so a second attempt costs no model call.
    assert await agent.title_session("alpha-1") is None
    assert len(model.requests) == 1


async def test_title_session_waits_for_a_reply(tmp_path):
    store = SessionStore(tmp_path)
    await store.append("alpha-2", "req", UserMessage(content="the parser crashes"))
    model = FakeModel()
    agent = ZettCodeAgent(FakeRuntime(store, model))

    assert await agent.title_session("alpha-2") is None
    assert model.requests == []


async def test_set_title_updates_the_index_and_the_newest_one_wins(tmp_path):
    store = SessionStore(tmp_path)
    await store.append("alpha-3", "req", UserMessage(content="hi"))

    await store.set_title("alpha-3", "  First name  ")
    await store.set_title("alpha-3", "Second name")

    assert store.session_title("alpha-3") == "Second name"
    # Renaming lives outside the conversation: the log keeps its one message.
    assert store.read("alpha-3").message_count == 1


async def test_set_title_rejects_a_bad_title(tmp_path):
    store = SessionStore(tmp_path)
    await store.append("alpha-4", "req", UserMessage(content="hi"))

    with pytest.raises(ValueError, match="between 1 and"):
        await store.set_title("alpha-4", "   ")
    with pytest.raises(ValueError, match="between 1 and"):
        await store.set_title("alpha-4", "x" * (MAX_TITLE + 1))


async def test_naming_a_session_that_has_not_been_used_creates_it(tmp_path):
    """Typing `/title` before the first message names a session, not a stray."""
    store = SessionStore(tmp_path)

    await store.set_title("alpha-5", "  Fix the parser crash  ")

    assert store.session_title("alpha-5") == "Fix the parser crash"
    # It is a real session now: it has a header and lists like any other, with
    # no conversation in it yet.
    assert store.read("alpha-5").header is not None
    assert store.read("alpha-5").message_count == 0
    assert [info.session_id for info in await store.list_sessions()] == ["alpha-5"]
