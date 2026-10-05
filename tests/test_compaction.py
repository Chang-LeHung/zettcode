"""``/compact``: the same compaction the runtime does, asked for on demand."""

from __future__ import annotations

from types import SimpleNamespace

from zett_agent.messages import AssistantMessage, SystemMessage, UserMessage
from zett_agent.model import ModelEvent, ModelResponse, RetryOptions

from zettcode.app.agent.compaction import OnDemandCompaction
from zettcode.app.agent.entries import EntryStatus, ThinkingEntry
from zettcode.app.agent.rows import COMPACTING_LABEL
from zettcode.app.agent.transcript import Transcript


class FakeModel:
    """The summarizer: one canned summary, no tools."""

    retry = RetryOptions(max_retries=0)

    def __init__(self, summary: str = "Earlier: the parser was fixed.") -> None:
        self.summary = summary
        self.requests: list[object] = []

    async def stream(self, request):
        self.requests.append(request)
        yield ModelEvent.text(self.summary)
        yield ModelEvent.completed(ModelResponse(AssistantMessage(content=self.summary)))


class FakeState:
    """Just the message list the extension reads and replaces."""

    def __init__(self, messages) -> None:
        self.messages = list(messages)


class FakeContext:
    """The slice of an ``AgentRunContext`` compaction touches."""

    def __init__(self, messages, model: FakeModel) -> None:
        self.state = FakeState(messages)
        self.config = SimpleNamespace(session_id="session-1")
        self.model = model
        self.emitted: list[object] = []
        self.published: list[object] = []

    async def emit(self, event) -> None:
        self.emitted.append(event)

    async def publish(self, event) -> None:
        self.published.append(event)

    def replace_messages(self, messages, *, emit_new: bool = True) -> None:
        self.state.messages = list(messages)


def _dialogue() -> list[object]:
    """A conversation small enough that no threshold would ever touch it."""
    return [
        SystemMessage(content="You are ZettCode."),
        UserMessage(content="the parser crashes"),
        AssistantMessage(content="I fixed the escaping"),
        UserMessage(content="does the suite pass?"),
        AssistantMessage(content="yes, all green"),
    ]


async def test_a_forced_pass_compacts_a_context_the_threshold_would_ignore():
    # A real budget: the automatic policy would keep a tail far larger than this
    # whole conversation, so only the forced pass can compact it.
    extension = OnDemandCompaction(None, max_tokens=1_000_000, keep_recent_tokens=200_000)
    context = FakeContext(_dialogue(), FakeModel())

    # The runtime reaches this through ``before_model``; the pass itself is the
    # public ``compact`` the extension now exposes.
    await extension.before_model(context, request=None)

    assert [message.content for message in context.state.messages] == [
        "You are ZettCode.",
        "the parser crashes",
        "I fixed the escaping",
        "does the suite pass?",
        "yes, all green",
    ]

    extension.request()

    assert extension.requested is True
    checkpoint = await extension.compact(context)

    assert extension.requested is False
    assert checkpoint is not None
    # The system instructions stay, the older dialogue is one checkpoint, and
    # the tail the policy keeps is still verbatim.
    messages = context.state.messages
    assert isinstance(messages[0], SystemMessage)
    assert "Conversation checkpoint" in messages[1].content
    assert "Earlier: the parser was fixed." in messages[1].content
    # The kept tail is a whole turn, not the single message the budget asked
    # for: the extension never splits a turn from the question that opened it.
    assert [message.content for message in messages[2:]] == ["does the suite pass?", "yes, all green"]
    assert context.published  # the checkpoint the persistence extension stores
    # Both budgets come back: the pass lent them to the parent, it did not keep them.
    assert (extension.max_tokens, extension.keep_recent_tokens) == (1_000_000, 200_000)


async def test_a_forced_pass_that_has_nothing_to_summarize_is_a_no_op():
    extension = OnDemandCompaction(None, max_tokens=1_000_000, keep_recent_tokens=32_000)
    context = FakeContext([UserMessage(content="hello")], FakeModel())

    extension.request()
    await extension.before_model(context, request=None)

    assert [message.content for message in context.state.messages] == ["hello"]
    assert extension.requested is False
    assert (extension.max_tokens, extension.keep_recent_tokens) == (1_000_000, 32_000)


def test_the_summarizer_gets_its_own_animated_row():
    """A compaction streams like reasoning, under its own label."""
    ticks = iter([10.0, 12.5])
    transcript = Transcript(clock=lambda: next(ticks))

    transcript.start_compaction()
    transcript.append_compaction("Earlier: ")
    transcript.append_compaction("the parser was fixed.")
    running = transcript.entries[-1]

    assert isinstance(running, ThinkingEntry)
    assert running.title == COMPACTING_LABEL
    assert running.status is EntryStatus.RUNNING

    transcript.complete_compaction()

    assert running.text == "Earlier: the parser was fixed."
    assert running.status is EntryStatus.COMPLETED
    assert running.duration == 2.5  # the row times itself, like a thinking row


def test_a_compaction_never_borrows_the_reasoning_row():
    """Both rows can be open at once, and each keeps its own text."""
    transcript = Transcript()

    transcript.start_thinking()
    transcript.append_thinking("weighing options")
    transcript.start_compaction()
    transcript.append_compaction("a checkpoint")
    transcript.complete_compaction()
    transcript.append_thinking(", still weighing")

    rows = [entry for entry in transcript.entries if isinstance(entry, ThinkingEntry)]
    assert [row.title for row in rows] == ["Thinking", COMPACTING_LABEL, "Thinking"]
    assert rows[0].text == "weighing options"
    assert rows[1].text == "a checkpoint"
    assert rows[2].text == ", still weighing"
