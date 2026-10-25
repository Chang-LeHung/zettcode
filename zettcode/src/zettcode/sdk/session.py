"""One conversation, and the runs made in it.

A :class:`Session` is a handle on a stored conversation. :meth:`Session.prompt` sends a prompt and returns a
:class:`RunStream`, which is both of the things a program wants from a run. Await it and you get the result::

    result = await session.prompt("fix the failing test")
    print(result.text)

Iterate it and you get the events as they happen, which is how a program shows progress, answers a shell approval,
or answers a question the model asked::

    async with session.prompt("fix the failing test") as run:
        async for event in run:
            if isinstance(event, TextDelta):
                print(event.text, end="")
    print(run.result.usage.total_tokens)

``stream`` and ``run`` are the same method under the names code written for other libraries tends to reach for.

A client has one run at a time, as the terminal application does, so a second run while one is in progress raises
:class:`~zettcode.sdk.errors.SessionBusyError` instead of interleaving two requests in one conversation.

This module imports nothing heavy at the top: the agent is loaded when a client is made, and the pieces that read its
messages are imported inside the functions that need them.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncGenerator, Callable, Generator, Sequence
from contextlib import aclosing
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Any, TypeAlias, cast

from .errors import (
    NothingToDoError,
    RunError,
    RunTimeoutError,
    SessionLockedError,
    SessionNotFoundError,
    ZettCodeError,
)
from .events import (
    AnyEvent,
    ApprovalRequested,
    Finished,
    ModelStopped,
    QuestionAsked,
    RawEvent,
    TextDelta,
    ToolFinished,
    ToolStarted,
)
from .handlers import ApprovalHandler, QuestionHandler, apply_approval, apply_question
from .types import (
    Compaction,
    ContextReport,
    ContextShare,
    Image,
    IncomingMessage,
    Message,
    ResumeInfo,
    RunResult,
    TaskInfo,
    ToolCallInfo,
    ToolRecord,
    Usage,
)

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from ..mentions import MentionRegistry
    from ..prompt import PromptPart
    from .client import Client

__all__ = ["Prompt", "RunStream", "Session"]

#: What a prompt is: text, or text and images in the order they should be read.
Prompt: TypeAlias = "str | Sequence[str | Image]"

#: What may be called with each event of a run; a coroutine function is awaited.
EventCallback: TypeAlias = Callable[[AnyEvent], object]


def _check_timeout(timeout: float | None) -> None:
    """Refuse a deadline that is not a positive number of seconds; ``None`` means no deadline."""
    if timeout is None:
        return
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not timeout > 0:
        raise ValueError("timeout must be a positive number of seconds, or None")


# -- the prompt -----------------------------------------------------------------------------------


def _prompt_parts(
    prompt: Prompt,
    images: Sequence[Image] = (),
    *,
    mentions: MentionRegistry | None = None,
    multimodal: bool = True,
    model_name: str = "the active model",
) -> tuple[tuple[PromptPart, ...], str | None]:
    """Return the parts a prompt makes up, and the instructions its ``@`` references add.

    Raises:
        TypeError: A piece of the prompt is not text or an :class:`Image`.
        ValueError: The prompt holds no text and no image.
        ConfigurationError: The prompt carries an image and the active model does not accept images.
    """
    from .errors import ConfigurationError

    pieces: list[str | Image] = [prompt] if isinstance(prompt, str) else list(prompt)
    pieces.extend(images)
    parts: list[Any] = []
    for piece in pieces:
        if isinstance(piece, str):
            parts.extend(_split_mentions(piece) if mentions is not None else [piece])
        elif isinstance(piece, Image):
            parts.append((bytes(piece.data), piece.media_type))
        else:
            raise TypeError(f"A prompt is text and images, not {type(piece).__name__}")
    # A part is text, an image (a tuple), or a reference to something with text of its own; only the first is
    # blank when it holds nothing but space.
    has_text = any((isinstance(p, str) and p.strip()) or not isinstance(p, (str, tuple)) for p in parts)
    has_image = any(isinstance(p, tuple) for p in parts)
    if not has_text and not has_image:
        raise ValueError("The prompt is empty")
    if has_image and not multimodal:
        raise ConfigurationError(
            f"{model_name} does not accept images; choose a multimodal model with use_model() or drop the images"
        )
    if mentions is None:
        return tuple(parts), None
    from ..prompt import mention_hint, mention_parts

    resolved = mention_parts(parts, mentions)
    return resolved, mention_hint(resolved, mentions)


def _split_mentions(text: str) -> list[Any]:
    """Split one text run at its ``@`` tokens, keeping the order, as the terminal's composer does."""
    from ..mentions import MENTION
    from ..prompt import MentionPart

    split: list[Any] = []
    cursor = 0
    for match in MENTION.finditer(text):
        if match.start() > cursor:
            split.append(text[cursor : match.start()])
        split.append(MentionPart(match.group(0)))
        cursor = match.end()
    if cursor < len(text):
        split.append(text[cursor:])
    return split


# -- the result a stream builds as it goes --------------------------------------------------------


@dataclass(slots=True)
class _Collector:
    """Accumulate the pieces of a :class:`RunResult` while the events go past."""

    keep_events: bool = False
    deltas: list[str] = field(default_factory=list)
    final: str | None = None
    tools: dict[str, ToolRecord] = field(default_factory=dict)
    stop: str | None = None
    stop_message: str | None = None
    questions: list[str] = field(default_factory=list)
    events: list[AnyEvent] = field(default_factory=list)

    @property
    def text(self) -> str:
        """Return the final answer, or what was streamed when the run ended without one."""
        return self.final if self.final else "".join(self.deltas)

    def see(self, event: AnyEvent) -> None:
        """Fold one event in."""
        if self.keep_events:
            self.events.append(event)
        if isinstance(event, TextDelta):
            self.deltas.append(event.text)
        elif isinstance(event, Finished):
            self.final = event.text
        elif isinstance(event, ToolStarted):
            self.tools[event.call_id] = ToolRecord(event.call_id, event.name, event.arguments, "", ok=False)
        elif isinstance(event, ToolFinished):
            before = self.tools.get(event.call_id)
            arguments = before.arguments if before is not None else {}
            self.tools[event.call_id] = ToolRecord(
                event.call_id, event.name, arguments, event.output, event.ok, event.skipped
            )
        elif isinstance(event, ModelStopped):
            self.stop, self.stop_message = event.reason, event.message
        elif isinstance(event, QuestionAsked):
            self.questions.append(event.question)

    def result(self, session_id: str, usage: Usage) -> RunResult:
        """Return the finished result."""
        return RunResult(
            text=self.text,
            session_id=session_id,
            usage=usage,
            tools=tuple(self.tools.values()),
            stop=self.stop,
            stop_message=self.stop_message,
            questions=tuple(self.questions),
            events=tuple(self.events),
        )


class _HandlerFailed(Exception):
    """A handler the program supplied raised; carried out of the stream untouched, not mistaken for a run failure."""

    def __init__(self, error: Exception) -> None:
        super().__init__(str(error))
        self.error = error


# -- one run --------------------------------------------------------------------------------------


class RunStream:
    """One run: await it for the result, or iterate it for the events.

    ::

        result = await session.prompt("explain this module")        # wait for the end
        async with session.prompt("explain this module") as run:    # or watch it happen
            async for event in run:
                ...

    Use ``async with`` when you may stop early, so the run is closed even if you leave the loop: a run that is not
    closed keeps the client busy until it is garbage collected. Awaiting closes it for you, and so does
    :meth:`aclose`. You can also do both: iterate part of it, then ``await`` the rest.

    Attributes:
        result: The :class:`RunResult`, or ``None`` until the run has ended on its own. A run stopped early or by an
            error has no result; :class:`~zettcode.sdk.errors.RunError` carries the text it had produced.
    """

    def __init__(
        self,
        session: Session,
        source: Callable[[], Any],
        *,
        on_approval: ApprovalHandler | None,
        on_question: QuestionHandler | None,
        on_event: EventCallback | None = None,
        timeout: float | None = None,
        raw: bool = False,
        keep_events: bool = False,
        side: bool = False,
        defer_answers: bool = False,
    ) -> None:
        _check_timeout(timeout)
        self._session = session
        self._client = session._client
        self._source = source
        self._on_approval = on_approval
        self._on_question = on_question
        self._on_event = on_event
        self._timeout = timeout
        self._deadline = 0.0
        self._raw = raw
        self._side = side
        self._defer = defer_answers
        #: The approvals and questions a deferred run left open past their event; whatever is still open when the
        #: run ends is denied or declined, so a suspended tool call never waits on a run that is over.
        self._open: list[ApprovalRequested | QuestionAsked] = []
        self._collector = _Collector(keep_events=keep_events)
        self._baseline = Usage()
        self._started = False
        self._finished = False
        self._closing = False
        self._pending: asyncio.Task[Any] | None = None
        self._gen = self._drive()
        self.result: RunResult | None = None

    # -- the iterator protocol --
    def __aiter__(self) -> RunStream:
        return self

    async def __anext__(self) -> AnyEvent:
        if self._finished and not self._started:
            raise StopAsyncIteration
        if not self._started:
            await self._begin()
        try:
            event = await self._next()
        except StopAsyncIteration:
            self._complete()
            raise
        except BaseException:
            self._release()
            raise
        if self._on_event is not None:
            try:
                outcome = self._on_event(event)
                if inspect.isawaitable(outcome):
                    await outcome
            except BaseException:
                await self.aclose()
                raise
        return event

    async def _next(self) -> AnyEvent:
        """Return the next event, within the run's deadline if it has one.

        Each step runs in a task of the stream's own. That is what lets :meth:`aclose` stop a run that another task
        is waiting on (a client closed under a reader, say) instead of finding the generator busy, and what lets a
        deadline stop a step without cancelling the caller.
        """
        if self._closing:
            raise StopAsyncIteration
        loop = asyncio.get_running_loop()
        remaining = None if self._timeout is None else self._deadline - loop.time()
        if remaining is not None and remaining <= 0:
            await self.aclose()
            raise RunTimeoutError(float(cast(float, self._timeout)), partial_text=self._collector.text)
        step = self._pending = loop.create_task(self._step())
        try:
            await asyncio.wait({step}, timeout=remaining)
        except BaseException:
            # The caller was cancelled while waiting. The step is no one's now, so it ends with them.
            await self._stop(step)
            raise
        finally:
            self._pending = None
        if not step.done():
            await self._stop(step)
            await self.aclose()
            raise RunTimeoutError(float(cast(float, self._timeout)), partial_text=self._collector.text)
        if step.cancelled():
            if self._closing:
                raise StopAsyncIteration  # the run was closed under this reader; its events are over
            raise asyncio.CancelledError
        return step.result()

    async def _step(self) -> AnyEvent:
        return await self._gen.__anext__()

    @staticmethod
    async def _stop(step: asyncio.Task[Any]) -> None:
        """Cancel a step and wait for it to unwind, whatever it ends with."""
        if not step.done():
            step.cancel()
        await asyncio.gather(step, return_exceptions=True)

    async def aclose(self) -> None:
        """Stop the run, if it is still going, and give the client back. Safe to call twice.

        Another task may be waiting for the next event of this very run; it is told the events are over.
        """
        self._closing = True
        self._release()
        pending = self._pending
        if pending is not None and pending is not asyncio.current_task():
            await self._stop(pending)
        await self._gen.aclose()

    async def __aenter__(self) -> RunStream:
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        await self.aclose()

    # -- awaiting --
    def __await__(self) -> Generator[Any, None, RunResult]:
        return self._wait().__await__()

    async def _wait(self) -> RunResult:
        """Take the rest of the events, and return the result."""
        async with self:
            async for _ in self:
                pass
        if self.result is None:
            raise RunError("The run ended without a result", partial_text=self._collector.text)
        return self.result

    # -- beginning and ending --
    async def _begin(self) -> None:
        """Take the client for this run: the session is made current, and the busy slot is claimed."""
        client = self._client
        client._check_open()
        client._claim(self)
        self._started = True
        try:
            await self._session._activate(self)
            self._baseline = self._session.usage
            if self._timeout is not None:
                self._deadline = asyncio.get_running_loop().time() + self._timeout
        except BaseException:
            self._release()
            raise

    def _release(self) -> None:
        self._finished = True
        self._client._release(self)

    def _complete(self) -> None:
        """The source ran dry: build the result from what went past, then give the client back."""
        if self.result is None:
            self.result = self._collector.result(self._session.id, self._session.usage.since(self._baseline))
        self._release()

    # -- the run --
    async def _drive(self) -> AsyncGenerator[AnyEvent, None]:
        """Pump the agent's events through ``translate``, answering the ones that wait on the program."""
        from .translation import translate

        agent = self._client._agent
        bridge = self._client._bridge
        runtime = agent.runtime
        # What a hosted tool's input has streamed so far, by call: a search may send its query in fragments, and the
        # end of the call is where the query is read.
        hosted: dict[str, str] = {}
        try:
            if self._side:
                runtime.sides.begin()
            try:
                async with aclosing(cast("AsyncGenerator[Any, None]", self._source())) as events:
                    async for raw in events:
                        if self._raw:
                            yield self._seen(RawEvent(raw.session_id or self._session.id, raw))
                        for event in translate(raw, bridge, hosted):
                            await self._answer(event)
                            self._hold(event)
                            yield self._seen(event)
                            self._settle(event)
            finally:
                for request in self._open:
                    self._default(request)
                self._open.clear()
                if self._side:
                    runtime.sides.end()
        except _HandlerFailed as failure:
            raise failure.error from None
        except Exception as error:
            translated = self._failure(error)
            if translated is error:
                raise
            raise translated from error

    def _seen(self, event: AnyEvent) -> AnyEvent:
        self._collector.see(event)
        return event

    async def _answer(self, event: AnyEvent) -> None:
        """Let the program's handler answer an approval or a question before the event is yielded."""
        try:
            if isinstance(event, ApprovalRequested):
                await apply_approval(event, self._on_approval)
            elif isinstance(event, QuestionAsked):
                await apply_question(event, self._on_question)
        except Exception as error:
            self._default(event)
            raise _HandlerFailed(error) from error

    def _hold(self, event: AnyEvent) -> None:
        """Remember a request a deferred run is about to yield unanswered, before it is yielded.

        Before, and not after: a consumer that stops at this very event never resumes the generator, and the run's end
        has to find the request to answer it.
        """
        if self._defer and isinstance(event, (ApprovalRequested, QuestionAsked)) and not event.answered:
            self._open.append(event)

    def _settle(self, event: AnyEvent) -> None:
        """Decide what an event that was yielded and not answered comes to.

        Normally it is denied or declined now. A deferred run keeps it open instead (see :meth:`_hold`), for the
        program to answer from wherever it asks the reader, and answers it for the program only when the run ends.
        """
        if self._defer and isinstance(event, (ApprovalRequested, QuestionAsked)):
            return
        self._default(event)

    @staticmethod
    def _default(event: AnyEvent) -> None:
        """Deny or decline what is still unanswered, so a suspended tool call never waits forever."""
        if isinstance(event, ApprovalRequested) and not event.answered:
            event.deny()
        elif isinstance(event, QuestionAsked) and not event.answered:
            event.decline()

    def _failure(self, error: Exception) -> Exception:
        """Return the SDK error that stands for ``error``, keeping the original as its cause."""
        from zett_agent.exceptions import AgentResumeError

        from ..engine.storage import SessionLocked
        from ..error_text import describe_error, may_pass

        if isinstance(error, ZettCodeError):
            return error
        if isinstance(error, SessionLocked):
            return SessionLockedError(str(error))
        if isinstance(error, AgentResumeError):
            return NothingToDoError(str(error))
        return RunError(describe_error(error), retryable=may_pass(error), partial_text=self._collector.text)


# -- the session ----------------------------------------------------------------------------------


class Session:
    """A conversation: run prompts in it, and read what it holds.

    Get one from ``client.session`` (the current conversation), ``client.sessions.new()``,
    ``await client.sessions.open(id)`` or :meth:`fork`. A handle stays valid when the client works on another
    conversation; the next call that needs this one switches back to it, unless a run is in progress.
    """

    def __init__(self, client: Client, session_id: str) -> None:
        self._client = client
        self.id = session_id

    def __repr__(self) -> str:
        return f"Session({self.id!r})"

    # -- what it is --
    @property
    def title(self) -> str | None:
        """Return the conversation's name, or ``None`` until it has one."""
        try:
            return self._client._agent.runtime.persistence.session_title(self.id)
        except (OSError, ValueError):
            return None

    @property
    def usage(self) -> Usage:
        """Return what this session has spent in total, in this process and, for a resumed one, before it."""
        from .translation import usage_from

        return usage_from(self._client._agent.runtime.usage.snapshot(self.id))

    @property
    def locked(self) -> bool:
        """Return whether another process has this session open, so it can be read and not changed."""
        runtime = self._client._agent.runtime
        return self.id == runtime.session_id and runtime.session_locked

    def tasks(self) -> tuple[TaskInfo, ...]:
        """Return the plan the model keeps for this session, in order; empty until it makes one."""
        self._client._check_open()
        if not self.current:
            return ()
        return tuple(TaskInfo(status, content) for status, content in self._client._agent.tasks())

    def retake(self) -> bool:
        """Try again to take the lock of a conversation another process had open, once that process has let go.

        Every conversation is locked by the process that has it open. One this client resumed may be somebody else's,
        and then it can be read and not changed (:attr:`locked`); a front end that shows it read-only can poll this and
        become the writer the moment the other one closes.

        Returns:
            Whether this client holds the lock now (also ``True`` when it already did, or the conversation is not the
            current one, which has no lock of its own to retake).

        Raises:
            ClientClosedError: The client was closed.
        """
        self._client._check_open()
        if self.id != self._client._agent.session_id:
            return True
        return self._client._agent.retake_session()

    @property
    def path(self) -> Path:
        """Return the file the conversation is stored in."""
        return self._client._agent.runtime.persistence.session_path(self.id)

    @property
    def current(self) -> bool:
        """Return whether this is the conversation the next run would use without switching."""
        return self._client._agent.session_id == self.id

    # -- running --
    def prompt(
        self,
        prompt: Prompt,
        *,
        images: Sequence[Image] = (),
        mentions: bool = False,
        on_approval: ApprovalHandler | None = None,
        on_question: QuestionHandler | None = None,
        on_event: EventCallback | None = None,
        timeout: float | None = None,
        raw: bool = False,
        keep_events: bool = False,
        defer_answers: bool = False,
    ) -> RunStream:
        """Send a prompt. Await the result of the call for the answer, or iterate it for the events.

        Args:
            prompt: Text, or text and :class:`Image` pieces in reading order.
            images: Images to put after the prompt.
            mentions: Resolve ``@skill`` and ``@path`` references the way the terminal does. Off by default, since
                ``@`` is also in email addresses and decorators.
            on_approval: Decides each shell command the permission level asks about; see
                :mod:`zettcode.sdk.handlers`. Without one, answer the :class:`ApprovalRequested` events yourself or
                they are denied.
            on_question: Answers each question the model asks. Without one, they are declined.
            on_event: Called with every event as it happens, for progress; may be a coroutine function.
            timeout: Seconds to allow the whole run; ``None`` waits as long as it takes.
            raw: Also yield the underlying ``zett-agent`` event as a :class:`RawEvent` before its typed events.
            keep_events: Keep every event in ``result.events``.
            defer_answers: Leave an approval or a question open past the event that asked it, so a program that asks
                its reader somewhere else (a panel, a chat) can answer it later with the event's own ``approve``,
                ``deny``, ``answer`` or ``decline``. Without it, one not answered by the time the stream is asked
                for its next event is denied or declined. Either way, whatever is still open when the run ends is.

        Raises:
            ValueError: The prompt is empty, or ``timeout`` is not a positive number.
            TypeError: A piece of the prompt is not text or an :class:`Image`.
            ConfigurationError: The prompt carries images and the model does not accept them.
            SessionBusyError: Another run is in progress (checked again when the run starts).
            ClientClosedError: The client was closed.
            RunTimeoutError: (when awaited or iterated) the run took longer than ``timeout``. It was stopped; what
                it had added to the conversation stays.
            RunError: (when awaited or iterated) the model, the provider or the network failed; ``retryable`` says
                whether trying again may help.
        """
        client = self._client
        client._check_open()
        client._check_free()
        _check_timeout(timeout)
        registry = client._mention_registry() if mentions else None
        model = client._agent.active_model
        parts, hint = _prompt_parts(
            prompt,
            images,
            mentions=registry,
            multimodal=model.multimodal,
            model_name=model.shown_name,
        )
        return RunStream(
            self,
            lambda: client._agent.stream(parts, hint=hint, side=False),
            on_approval=on_approval,
            on_question=on_question,
            on_event=on_event,
            timeout=timeout,
            raw=raw,
            keep_events=keep_events,
            defer_answers=defer_answers,
        )

    #: The same method as :meth:`prompt`; it returns a stream you can iterate, which is what the name says.
    stream = prompt

    def relay(
        self,
        message: IncomingMessage,
        *,
        on_approval: ApprovalHandler | None = None,
        on_question: QuestionHandler | None = None,
        on_event: EventCallback | None = None,
        timeout: float | None = None,
        raw: bool = False,
        keep_events: bool = False,
        defer_answers: bool = False,
    ) -> RunStream:
        """Run one turn for a message another session sent.

        The message is what the model reads — framed with where it came from, and with the instruction that an
        answer here goes only to this session's reader — and the text as sent is what a restored conversation
        shows.

        Raises:
            ClientClosedError: The client was closed.
            SessionBusyError: Another run is in progress (checked again when the run starts).
            ValueError: ``timeout`` is not a positive number.
        """
        from ..relay import Relayed

        client = self._client
        client._check_open()
        client._check_free()
        _check_timeout(timeout)
        relayed = Relayed(
            sender_id=message.sender_id,
            sender=message.sender,
            text=message.text,
            via=message.via,
            hops=message.hops,
        )
        return RunStream(
            self,
            lambda: client._agent.stream((), relayed=relayed),
            on_approval=on_approval,
            on_question=on_question,
            on_event=on_event,
            timeout=timeout,
            raw=raw,
            keep_events=keep_events,
            defer_answers=defer_answers,
        )

    async def run(
        self,
        prompt: Prompt,
        *,
        images: Sequence[Image] = (),
        mentions: bool = False,
        on_approval: ApprovalHandler | None = None,
        on_question: QuestionHandler | None = None,
        on_event: EventCallback | None = None,
        timeout: float | None = None,
        keep_events: bool = False,
    ) -> RunResult:
        """Send a prompt and wait for the model to finish; ``await session.prompt(...)`` spelled as a call.

        Takes the arguments, and raises the errors, of :meth:`prompt`.
        """
        return await self.prompt(
            prompt,
            images=images,
            mentions=mentions,
            on_approval=on_approval,
            on_question=on_question,
            on_event=on_event,
            timeout=timeout,
            keep_events=keep_events,
        )

    def ask_stream(
        self, question: str, *, on_event: EventCallback | None = None, timeout: float | None = None
    ) -> RunStream:
        """Ask a side question and return the stream of its answer, so it can be shown as it is written.

        The same side question as :meth:`ask`: the model sees the whole conversation and answers on a read-only
        footing, and neither the question nor the answer joins the history. Iterate the stream for its events
        (``TextDelta`` carries the answer as it arrives), or await it for the result.

        Raises:
            ValueError: The question is empty.
            SessionBusyError: A run is in progress.
        """
        client = self._client
        client._check_open()
        client._check_free()
        if not isinstance(question, str) or not question.strip():
            raise ValueError("The question is empty")
        parts: tuple[Any, ...] = (question,)
        return RunStream(
            self,
            lambda: client._agent.stream(parts, side=True),
            on_approval=None,
            on_question=None,
            on_event=on_event,
            timeout=timeout,
            side=True,
        )

    async def ask(
        self,
        question: str,
        *,
        on_event: EventCallback | None = None,
        timeout: float | None = None,
    ) -> str:
        """Ask a side question about the conversation and return the answer, without adding to it.

        The model sees the whole conversation and answers on a read-only footing; neither the question nor the
        answer joins the history the next run is built from. :meth:`ask_stream` is the same question with the
        answer streamed.

        Raises:
            ValueError: The question is empty.
        """
        return (await self.ask_stream(question, on_event=on_event, timeout=timeout)).text

    def steer(self, message: str) -> bool:
        """Send a message to the run in progress, which drops what it was doing to take it into account.

        Returns:
            Whether a running request took it. ``False`` when nothing is running in this session, and for a blank
            message; nothing is queued for later.
        """
        client = self._client
        running = client._stream
        if client._closed or running is None or running._session.id != self.id or not isinstance(message, str):
            return False
        return client._agent.steer(message)

    async def resumable(self) -> ResumeInfo | None:
        """Say where the conversation was interrupted and what :meth:`resume` would do; ``None`` if it was not."""
        from ..engine.storage import SessionLocked

        await self._activate()
        try:
            point = await self._client._agent.resume_point()
        except SessionLocked as error:
            raise SessionLockedError(str(error)) from error
        return None if point is None else ResumeInfo(str(point.kind.value), point.description)

    def resume_stream(
        self,
        *,
        on_approval: ApprovalHandler | None = None,
        on_question: QuestionHandler | None = None,
        on_event: EventCallback | None = None,
        timeout: float | None = None,
        raw: bool = False,
        keep_events: bool = False,
        defer_answers: bool = False,
    ) -> RunStream:
        """Pick up an interrupted request where it stopped; await it or iterate it like :meth:`prompt`.

        Raises:
            NothingToDoError: Awaiting or iterating raises it when there is nothing to pick up, with the reason.
        """
        client = self._client
        client._check_open()
        client._check_free()
        return RunStream(
            self,
            lambda: client._agent.stream_resume(),
            on_approval=on_approval,
            on_question=on_question,
            on_event=on_event,
            timeout=timeout,
            raw=raw,
            keep_events=keep_events,
            defer_answers=defer_answers,
        )

    async def resume(
        self,
        *,
        on_approval: ApprovalHandler | None = None,
        on_question: QuestionHandler | None = None,
        on_event: EventCallback | None = None,
        timeout: float | None = None,
    ) -> RunResult:
        """Pick up an interrupted request where it stopped and wait for it to finish (see :meth:`resume_stream`)."""
        return await self.resume_stream(
            on_approval=on_approval, on_question=on_question, on_event=on_event, timeout=timeout
        )

    # -- working on the conversation --
    async def compact(self) -> Compaction | None:
        """Summarize the older part of the conversation now, to make room, without adding a turn.

        Returns:
            What was done, or ``None`` when there was nothing worth folding.

        Raises:
            NothingToDoError: The conversation is already compacted up to its newest message.
            SessionLockedError: Another process has the session open.
        """
        from ..engine.storage import SessionLocked
        from ..error_text import describe_error, may_pass

        client = self._client
        client._check_open()
        client._check_free()
        await self._activate()
        try:
            event = await client._agent.compact()
        except SessionLocked as error:
            raise SessionLockedError(str(error)) from error
        except ValueError as error:
            raise NothingToDoError(str(error)) from error
        except Exception as error:
            raise RunError(describe_error(error), retryable=may_pass(error)) from error
        if event is None:
            return None
        return Compaction(
            event.summary,
            max(0, event.compressed_to - event.compressed_from + 1),
            max(0, event.kept_to - event.kept_from + 1),
        )

    async def context(self) -> ContextReport | None:
        """Report what the next request would carry, by source; ``None`` before the first reply."""
        self._client._check_open()
        await self._activate()
        report = await self._client._agent.context_report()
        if report is None:
            return None
        return ContextReport(
            window=report.window,
            used=report.used,
            measured_by=report.measured_by,
            shares=tuple(ContextShare(share.name, share.tokens, share.items) for share in report.shares),
            partial=report.partial,
            from_provider=report.from_provider,
        )

    async def rename(self, title: str) -> str:
        """Give the conversation a name and return it as stored (trimmed).

        Raises:
            ValueError: The title is blank or too long.
            SessionLockedError: Another process has the session open.
        """
        from ..engine.storage import SessionLocked

        self._client._check_open()
        if not self.current:
            # Naming another conversation switches to it, which a run in progress forbids. Naming the current one
            # only writes its title, which a run does not read, so it may be done beside one.
            self._client._check_free()
        await self._activate()
        try:
            return await self._client._agent.rename_session(title)
        except SessionLocked as error:
            raise SessionLockedError(str(error)) from error

    async def name_it(self) -> str | None:
        """Ask the model for a short title from the first exchange, unless one exists; return the session's title.

        A session that already has a title keeps it and the model is not asked. ``None`` means there was no
        exchange to name yet, or the model gave nothing usable.
        """
        self._client._check_open()
        await self._activate()
        return await self._client._agent.title_session(self.id) or self.title

    async def export(self, path: str | Path | None = None) -> Path:
        """Write the conversation out as a page and return where it went.

        Args:
            path: Where to write it; ``None`` writes ``zettcode-<id8>.html`` in the workspace. A relative path is taken
                from the working directory.

        Raises:
            ValueError: The session has nothing stored yet.
        """
        self._client._check_open()
        await self._activate()
        return await self._client._agent.export_session(path)

    async def fork(self) -> Session:
        """Copy the conversation's context into a new session and return it; this one is left as it is."""
        client = self._client
        client._check_open()
        client._check_free()
        await self._activate()
        try:
            new_id = await asyncio.to_thread(client._agent.fork_session)
        except (ValueError, OSError) as error:
            raise SessionNotFoundError(str(error)) from error
        return client._handle(new_id)

    async def history(self, *, full: bool = False) -> list[Message]:
        """Return the messages the model is working with: the compaction summary if any, then what followed it.

        With ``full=True`` it returns the whole conversation on the active branch instead, as it was written: the
        messages a compaction folded away are there, and each summary stands (as a ``summary`` message) at the
        point where it was made. That is what a client shows when it reopens a session; the model still works from
        the shorter list.

        Reading needs no lock, so this works on a session another process has open.

        Raises:
            SessionNotFoundError: The session has not been written yet, or its file cannot be read.
        """
        self._client._check_open()
        persistence = self._client._agent.runtime.persistence
        try:
            stored = await asyncio.to_thread(persistence.read, self.id)
        except (ValueError, OSError) as error:
            raise SessionNotFoundError(f"Cannot read session {self.id}: {error}") from error
        if stored.header is None:
            raise SessionNotFoundError(f"Session {self.id} has no messages yet")
        entries: list[tuple[Any, Any, float]] = []
        if full:
            branch = stored.branch()
            on_branch = {line.id for line in branch}
            summaries: dict[str, list[Any]] = {}
            for compaction in sorted(stored.compactions, key=lambda line: line.version):
                if compaction.parent in on_branch:
                    summaries.setdefault(compaction.parent, []).append(compaction)
            for line in branch:
                if line.message[0].include_in_messages:
                    entries.append((line.message[0], line.usage, line.timing.duration_ns / 1e9))
                entries.extend((compaction.message[0], None, 0.0) for compaction in summaries.get(line.id, []))
        else:
            checkpoint, tail = stored.active()
            if checkpoint is not None:
                entries.append((checkpoint.message[0], None, 0.0))
            for line in tail:
                if line.message[0].include_in_messages:
                    entries.append((line.message[0], line.usage, line.timing.duration_ns / 1e9))
        return [
            message for item, usage, seconds in entries if (message := _message_of(item, usage, seconds)) is not None
        ]

    # -- becoming the current conversation --
    async def _activate(self, by: RunStream | None = None) -> None:
        """Make this the client's current conversation, unless it is already."""
        await self._client._switch_to(self.id, by)


def _message_of(item: object, usage: Any = None, seconds: float = 0.0) -> Message | None:
    """Return the SDK's view of one stored message; system and bookkeeping messages are not part of the history.

    ``usage`` is what the store recorded for the model call that produced the message, and ``seconds`` how long it took.
    """
    from zett_agent.extensions.compaction import CompactedMessage
    from zett_agent.messages import AssistantMessage, ImageBytesSource, ImageContent, ToolMessage, UserMessage

    # The summary that stands in for the older messages is a user message to the model, but nobody typed it.
    if isinstance(item, CompactedMessage):
        return Message("summary", item.text)
    if isinstance(item, UserMessage):
        typed = item.attributes.get("prompt")
        text = typed if isinstance(typed, str) else item.text
        pictures = tuple(
            Image(part.source.data, part.source.media_type)
            for part in item.parts
            if isinstance(part, ImageContent) and isinstance(part.source, ImageBytesSource) and part.source.data
        )
        images = sum(1 for part in item.parts if isinstance(part, ImageContent))
        return Message("user", text, images=images, pictures=pictures)
    if isinstance(item, AssistantMessage):
        calls = tuple(ToolCallInfo(call.id, call.name, dict(call.arguments)) for call in item.tool_calls)
        spent = (
            None
            if usage is None
            else Usage(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_tokens=usage.cache_read_tokens,
                cache_write_tokens=usage.cache_write_tokens,
                reasoning_tokens=usage.reasoning_tokens,
                seconds=seconds,
                requests=1,
            )
        )
        return Message(
            "assistant",
            item.content if isinstance(item.content, str) else "",
            tool_calls=calls,
            usage=spent,
            seconds=seconds,
        )
    if isinstance(item, ToolMessage):
        images = (
            0 if isinstance(item.content, str) else sum(1 for part in item.content if isinstance(part, ImageContent))
        )
        return Message(
            "tool",
            item.text,
            tool_call_id=item.tool_call_id,
            tool_name=item.name,
            ok=item.success,
            images=images,
            seconds=seconds,
        )
    return None
