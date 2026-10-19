"""The events a run produces, as plain typed values.

``zett-agent`` streams one ``AgentEvent`` with a type tag and a set of optional fields whose meaning depends on the
tag, and the application's own extras (a shell approval, a question for the reader, token totals) ride on it as
``CUSTOM`` events with a name and a loose payload. This module turns that into one frozen dataclass per thing that
happened, so a program matches on a class and reads fields that are always there::

    async for event in session.stream("fix the failing test"):
        match event:
            case TextDelta(text=text):
                print(text, end="")
            case ApprovalRequested() as ask:
                ask.approve() if "rm " not in ask.command else ask.deny()

Two events ask something of the program: :class:`ApprovalRequested` and :class:`QuestionAsked`. The agent is
suspended inside the tool call until they are answered, which is why each carries the methods that answer it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, TypeAlias

from .types import Compaction, Usage

if TYPE_CHECKING:  # pragma: no cover - annotations only; nothing here imports the agent
    from collections.abc import Callable

    from zett_agent.events import AgentEvent

    from ..app.agent.dialogue.ask import AskUserQuestion

__all__ = [
    "AnyEvent",
    "ApprovalRequested",
    "CompactionFinished",
    "CompactionStarted",
    "Event",
    "Finished",
    "ModelStopped",
    "Notice",
    "QuestionAsked",
    "RawEvent",
    "ReasoningDelta",
    "Steered",
    "TextDelta",
    "ToolFinished",
    "ToolStarted",
    "UsageUpdated",
]


class Bridge(Protocol):
    """How an answer reaches the suspended agent; the client supplies it."""

    def approve(self, session_id: str, call_id: str, approve: bool, remember: bool) -> None:
        """Send a shell approval decision."""

    def answer(self, question: AskUserQuestion, text: str | None) -> None:
        """Send the answer to a question, or decline it when ``text`` is ``None``."""


class _Reply:
    """The one-shot slot an answerable event settles through.

    The first answer wins and is sent exactly once. Asking again for the same thing is harmless, and asking for the
    opposite is a mistake worth raising, because the agent has already acted on the first.
    """

    __slots__ = ("_send", "outcome")

    def __init__(self, send: Callable[[object], None]) -> None:
        self._send = send
        self.outcome: object | None = None

    def settle(self, outcome: object) -> None:
        """Send ``outcome`` unless an answer was already sent; raise if the earlier one differs."""
        if self.outcome is not None:
            if self.outcome != outcome:
                raise ValueError(f"Already answered ({self.outcome!r}); it cannot be answered again as {outcome!r}")
            return
        self._send(outcome)
        self.outcome = outcome


@dataclass(frozen=True, slots=True)
class Event:
    """Base of every event.

    Attributes:
        session_id: The session the run belongs to.
    """

    session_id: str


@dataclass(frozen=True, slots=True)
class TextDelta(Event):
    """A piece of the model's answer.

    Attributes:
        text: The new text, to be appended to what came before.
    """

    text: str


@dataclass(frozen=True, slots=True)
class ReasoningDelta(Event):
    """A piece of the model's reasoning, for the providers that report it.

    Attributes:
        text: The new text.
    """

    text: str


@dataclass(frozen=True, slots=True)
class ToolStarted(Event):
    """The model called a tool and it is starting.

    Attributes:
        call_id: Identity that ties this to its :class:`ToolFinished`.
        name: The tool.
        arguments: What it was called with.
    """

    call_id: str
    name: str
    arguments: dict[str, object]


@dataclass(frozen=True, slots=True)
class ToolFinished(Event):
    """A tool call ended, in success, in failure, or because it never ran.

    Attributes:
        call_id: The call it answers.
        name: The tool.
        output: What the tool returned, or the failure text.
        ok: Whether it succeeded.
        skipped: Whether it never ran because steering took over.
    """

    call_id: str
    name: str
    output: str
    ok: bool
    skipped: bool = False


@dataclass(frozen=True, slots=True)
class ApprovalRequested(Event):
    """The model wants to run a shell command and the permission level asks first.

    The agent waits until this is answered. Call :meth:`approve` or :meth:`deny` before asking the stream for its
    next event; a request still unanswered by then is denied, so an unattended run never hangs. A handler passed to
    the run answers before the event is yielded, and then :attr:`answered` is already true.

    Attributes:
        call_id: The tool call the answer belongs to.
        command: The command the model wants to run.
        timeout_seconds: The limit the command would run under, when the tool states one.
        remember_supported: Whether approving can be remembered for the rest of the run.
    """

    call_id: str
    command: str
    timeout_seconds: int | None = None
    remember_supported: bool = False
    _reply: _Reply | None = field(default=None, repr=False, compare=False)

    def approve(self, *, remember: bool = False) -> None:
        """Let the command run; ``remember`` also lets the same kind of command run unasked afterwards."""
        remember = remember and self.remember_supported
        self._settle(("execute", remember))

    def deny(self) -> None:
        """Refuse the command; the model is told, and carries on without it."""
        self._settle(("abort", False))

    @property
    def answered(self) -> bool:
        """Return whether it was answered, by the program or by the run's handler."""
        return self._reply is not None and self._reply.outcome is not None

    @property
    def approved(self) -> bool | None:
        """Return the answer: ``True`` approved, ``False`` denied, ``None`` while unanswered."""
        outcome = self._reply.outcome if self._reply is not None else None
        return None if outcome is None else outcome[0] == "execute"  # type: ignore[index]

    def _settle(self, outcome: tuple[str, bool]) -> None:
        if self._reply is None:
            raise RuntimeError("This request was not created by a run, so there is nothing to answer")
        self._reply.settle(outcome)


@dataclass(frozen=True, slots=True)
class QuestionAsked(Event):
    """The model asked the reader a question and waits for the answer.

    Call :meth:`answer` or :meth:`decline` before asking the stream for its next event. A question still unanswered
    by then is declined, which tells the model the reader cancelled, so an unattended run never hangs.

    Attributes:
        call_id: The tool call the answer belongs to.
        question: What it asked.
        options: The choices it offered, if any; the answer may still be free text.
        allow_multiple: Whether more than one option may be chosen.
    """

    call_id: str
    question: str
    options: tuple[str, ...] = ()
    allow_multiple: bool = False
    _reply: _Reply | None = field(default=None, repr=False, compare=False)

    def answer(self, text: str) -> None:
        """Answer it. The text goes to the model exactly as given (join several choices yourself)."""
        if not isinstance(text, str) or not text.strip():
            raise ValueError("An answer cannot be empty; call decline() to refuse the question")
        self._settle(text)

    def decline(self) -> None:
        """Tell the model the question was cancelled."""
        self._settle(None)

    @property
    def answered(self) -> bool:
        """Return whether it was answered or declined."""
        return self._reply is not None and self._reply.outcome is not None

    def _settle(self, outcome: str | None) -> None:
        if self._reply is None:
            raise RuntimeError("This question was not created by a run, so there is nothing to answer")
        self._reply.settle(("answer", outcome))


@dataclass(frozen=True, slots=True)
class UsageUpdated(Event):
    """The session's token totals after a model call.

    Attributes:
        usage: Cumulative for the session, not for this run; ``RunResult.usage`` is the run's own.
    """

    usage: Usage


@dataclass(frozen=True, slots=True)
class CompactionStarted(Event):
    """The conversation is being summarized to make room."""


@dataclass(frozen=True, slots=True)
class CompactionFinished(Event):
    """A compaction ended.

    Attributes:
        applied: Whether it replaced the context; ``False`` when there was nothing worth folding.
        compaction: What it did, when it applied.
    """

    applied: bool
    compaction: Compaction | None = None


@dataclass(frozen=True, slots=True)
class ModelStopped(Event):
    """A model step ended for a reason other than finishing: refused, cut off, interrupted, paused.

    Attributes:
        reason: ``refusal``, ``max_output``, ``context_full``, ``paused``, ``interrupted`` or ``other``.
        message: The provider's sentence about it, when it gave one.
    """

    reason: str
    message: str | None = None


@dataclass(frozen=True, slots=True)
class Steered(Event):
    """A message sent with ``steer`` reached the running request.

    Attributes:
        text: What was said.
    """

    text: str


@dataclass(frozen=True, slots=True)
class Notice(Event):
    """News that is not part of the answer, such as an MCP server that could not be reached.

    Attributes:
        text: One readable line.
        level: How serious it is: ``"info"`` for progress (an MCP server is starting, or ready) and ``"warn"`` for
            something the reader may need to act on (a server is down, a configuration entry is ignored).
    """

    text: str
    level: str = "info"


@dataclass(frozen=True, slots=True)
class Finished(Event):
    """The run ended and the model has given its final answer.

    Attributes:
        text: The answer, which may be empty if the model only used tools.
    """

    text: str


@dataclass(frozen=True, slots=True)
class RawEvent(Event):
    """The underlying ``zett-agent`` event, for a program that wants what the SDK does not model.

    Only produced when a run is started with ``raw=True``, and always *in addition to* the typed events.

    Attributes:
        event: The event as ``zett-agent`` produced it.
    """

    event: AgentEvent


#: Every event a run can yield.
AnyEvent: TypeAlias = (
    TextDelta
    | ReasoningDelta
    | ToolStarted
    | ToolFinished
    | ApprovalRequested
    | QuestionAsked
    | UsageUpdated
    | CompactionStarted
    | CompactionFinished
    | ModelStopped
    | Steered
    | Notice
    | Finished
    | RawEvent
)
