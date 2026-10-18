"""The one agent a server process owns: who may run, and how a run's events reach a client.

A server serves one workspace, so it has one client and one conversation at a time — the same rule the terminal and
the SDK follow. A prompt that arrives while another runs is refused with ``busy`` instead of queued: the caller can
see that nothing happened, and a long run is never silently joined by a second.

A run started over HTTP has no terminal to answer it, so the answers travel with the request or over the endpoints
that post back into the run: :class:`~zettcode_server.schemas.ApprovalPolicy` decides shell commands up front
(``deny``, ``auto``, ``commands``) or defers each one to the client (``ask``); questions are declined unless the
request says ``questions: ask``. A deferred request waits for ``POST /runs/approvals`` or ``POST /runs/questions``
for ``answer_timeout`` seconds and then takes the safe default, so no client can leave a run suspended forever.
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, cast

from zettcode.sdk.errors import SessionBusyError
from zettcode.sdk.events import ApprovalRequested, QuestionAsked
from zettcode.sdk.handlers import ApprovalHandler, approve_all, approve_commands, deny_all

from .schemas import ApprovalPolicy, PendingOut, PromptRequest, ResumeRequest
from .serialize import event_payload, result_out

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zettcode.sdk.client import Client, RunStream
    from zettcode.sdk.types import (
        Image,
        MentionInfo,
        ModelCheck,
        ResumeInfo,
        RunResult,
        SessionStatsInfo,
        WorkspaceUsage,
    )

    from .settings import Settings

#: Builds the client the server runs on; the tests pass one that answers without a model.
ClientFactory = Callable[[], "Client"]

#: One frame of a run: its SSE event name, and the JSON payload under it.
Frame = tuple[str, dict[str, object]]

#: What a run may be asked to do, whether it starts a prompt or continues one.
Request = PromptRequest | ResumeRequest


def approval_handler(policy: ApprovalPolicy) -> ApprovalHandler | None:
    """Return the handler a run answers shell commands with, or ``None`` when the client is asked instead.

    Raises:
        ValueError: ``commands`` names a command that is blank or holds a shell character, which the SDK refuses
            because ``git status; rm -rf ~`` begins with an approved command too.
    """
    if policy.mode == "auto":
        return approve_all
    if policy.mode == "commands":
        return approve_commands(*policy.commands)
    if policy.mode == "ask":
        return None
    return deny_all


def images_of(request: Request) -> tuple[Image, ...]:
    """Return the pictures a prompt carries, decoded.

    Raises:
        ValueError: The base64 is not base64, or a picture is of a type no model takes.
    """
    from zettcode.sdk.types import Image

    images = getattr(request, "images", ())
    decoded: list[Image] = []
    for entry in images:
        try:
            data = base64.b64decode(entry.data, validate=True)
        except Exception as error:  # noqa: BLE001 - any decoding failure is the same client mistake
            raise ValueError(f"The image data is not valid base64: {error}") from error
        decoded.append(Image(data, entry.media_type))
    return tuple(decoded)


def prepare(request: Request) -> None:
    """Refuse a request that cannot run before its stream opens, where a status code still reaches the client."""
    approval_handler(request.approvals)
    images_of(request)


@dataclass
class Pending:
    """An approval or a question the run is suspended on, and the slot its answer settles.

    Attributes:
        kind: What is waiting.
        call_id: The tool call it belongs to, as the client saw it in the stream.
        event: The SDK event to answer.
        answered: Set once an answer arrived; the run stops waiting on it.
    """

    kind: Literal["approval", "question"]
    call_id: str
    event: ApprovalRequested | QuestionAsked
    answered: asyncio.Event = field(default_factory=asyncio.Event)

    def describe(self) -> PendingOut:
        """Return what a reconnecting client needs to show the request again."""
        if isinstance(self.event, ApprovalRequested):
            return PendingOut(
                kind="approval",
                call_id=self.call_id,
                command=self.event.command,
                timeout_seconds=self.event.timeout_seconds,
                remember_supported=self.event.remember_supported,
            )
        return PendingOut(
            kind="question",
            call_id=self.call_id,
            question=self.event.question,
            options=list(self.event.options),
            allow_multiple=self.event.allow_multiple,
        )


class Runner:
    """The agent, one run at a time, and the events and answers of the run that is going.

    Args:
        settings: The workspace and the level a run starts at.
        factory: Builds the client; by default an SDK :class:`~zettcode.sdk.Client` on the settings' workspace.
    """

    def __init__(self, settings: Settings, factory: ClientFactory | None = None) -> None:
        self.settings = settings
        self._factory = factory
        self._client: Client | None = None
        self._run: RunStream | None = None
        self._pending: Pending | None = None
        self._lock = asyncio.Lock()

    # -- life -----------------------------------------------------------------
    async def start(self) -> None:
        """Open the client. The SDK starts the agent, not a model, so this reaches no provider."""
        if self._client is not None:
            return
        if self._factory is None:
            from zettcode.sdk import Client

            self._client = await asyncio.to_thread(
                lambda: Client(
                    self.settings.workspace,
                    config_path=self.settings.config_path,
                    model=self.settings.model,
                    effort=self.settings.effort,
                    permission=self.settings.permission,
                )
            )
        else:
            self._client = self._factory()

    async def close(self) -> None:
        """Stop anything still running and close the client, which releases the session lock."""
        await self.cancel()
        client, self._client = self._client, None
        if client is not None:
            await client.aclose()

    @property
    def client(self) -> Client:
        """Return the open client.

        Raises:
            RuntimeError: The server was used before its lifespan started.
        """
        if self._client is None:
            raise RuntimeError("The server has no client: its lifespan did not run")
        return self._client

    @property
    def busy(self) -> bool:
        """Return whether a prompt is running."""
        return self._lock.locked()

    @property
    def pending(self) -> PendingOut | None:
        """Return the approval or question the run waits on, if it is waiting on one."""
        return None if self._pending is None else self._pending.describe()

    # -- running --------------------------------------------------------------
    async def stream(self, request: Request, *, resume: bool = False) -> AsyncIterator[Frame]:
        """Run one prompt, or continue an interrupted one, and yield its events and then its result.

        The stream ends with ``result`` when the model finished, ``error`` when the run failed, and ``cancelled`` when
        it was stopped from outside — a closed connection included, which is what stops a run whose reader is gone.
        """
        if self._lock.locked():
            raise SessionBusyError("A run is already in progress; wait for it or cancel it")
        handler = approval_handler(request.approvals)
        images = images_of(request)
        await self._lock.acquire()
        run: RunStream | None = None
        try:
            run = self._start(request, handler, images, resume)
            self._run = run
            async for event in run:
                yield "event", event_payload(event)
                note = await self._settle(event, request)
                if note:
                    yield "event", {"type": "notice", "text": note}
            result = run.result
            if result is None:
                yield "cancelled", {"type": "cancelled"}
            else:
                yield "result", result_payload(result)
        finally:
            self._pending = None
            run, self._run = self._run, None
            if run is not None:
                await run.aclose()
            self._lock.release()

    def _start(
        self, request: Request, handler: ApprovalHandler | None, images: tuple[Image, ...], resume: bool
    ) -> RunStream:
        """Start the SDK's run; kept apart so a failure to start does not look like a failure mid-stream."""
        session = self.client.session
        if resume:
            return session.resume_stream(on_approval=handler, timeout=request.timeout, keep_events=request.keep_events)
        prompt = cast(PromptRequest, request)
        return self.client.prompt(
            prompt.text,
            images=images,
            mentions=prompt.mentions,
            on_approval=handler,
            timeout=request.timeout,
            keep_events=request.keep_events,
        )

    async def _settle(self, event: object, request: Request) -> str | None:
        """Wait for the client's answer when the request asked for one; return a note when none came.

        Called after the event has gone down the stream and before the next one is asked for, which is exactly the
        window in which the SDK leaves a request unanswered and has not yet applied its own default.
        """
        if isinstance(event, ApprovalRequested) and request.approvals.mode == "ask":
            note = await self._hold(Pending("approval", event.call_id, event), request.answer_timeout)
            if note and not event.answered:
                event.deny()
            return note
        if isinstance(event, QuestionAsked) and request.questions == "ask":
            note = await self._hold(Pending("question", event.call_id, event), request.answer_timeout)
            if note and not event.answered:
                event.decline()
            return note
        return None

    async def _hold(self, pending: Pending, seconds: float) -> str | None:
        """Publish a pending request and wait for its answer; return why it was given up on, or ``None``."""
        self._pending = pending
        try:
            await asyncio.wait_for(pending.answered.wait(), seconds)
            return None
        except asyncio.TimeoutError:
            if pending.kind == "approval":
                return f"No answer within {seconds:g}s; the command was denied."
            return f"No answer within {seconds:g}s; the question was declined."
        finally:
            self._pending = None

    async def resolve_approval(self, call_id: str, approve: bool, remember: bool = False) -> bool:
        """Answer the approval the run waits on; ``False`` when it names one that is not waiting."""
        pending = self._pending
        if pending is None or pending.kind != "approval" or pending.call_id != call_id:
            return False
        event = cast(ApprovalRequested, pending.event)
        if event.answered:
            return False
        event.approve(remember=remember) if approve else event.deny()
        pending.answered.set()
        return True

    async def resolve_question(self, call_id: str, answer: str | None) -> bool:
        """Answer, or decline with ``None``, the question the run waits on."""
        pending = self._pending
        if pending is None or pending.kind != "question" or pending.call_id != call_id:
            return False
        event = cast(QuestionAsked, pending.event)
        if event.answered:
            return False
        event.answer(answer) if answer is not None else event.decline()
        pending.answered.set()
        return True

    async def cancel(self) -> bool:
        """Stop the run in progress, if there is one, and return whether there was.

        The stream of a cancelled run sees its events end and reports ``cancelled``; its reader is not an error.
        """
        run = self._run
        if run is None:
            return False
        await run.aclose()
        return True

    # -- the conversation, without running it --------------------------------
    def steer(self, message: str) -> bool:
        """Send a message into the run in progress; ``False`` when nothing is running to take it."""
        return self.client.session.steer(message)

    async def resumable(self) -> ResumeInfo | None:
        """Return where the conversation was interrupted, or ``None`` when it was not."""
        return await self.client.session.resumable()

    # -- what a terminal shows around the conversation -----------------------
    async def mentions(self, query: str, limit: int) -> tuple[MentionInfo, ...]:
        """Return the ``@`` resources matching ``query``; the workspace walk runs off the event loop."""
        return await asyncio.to_thread(self.client.mentions, query, limit=limit)

    async def usage_ledger(self) -> WorkspaceUsage:
        """Return what every stored session of the workspace spent."""
        return await self.client.usage_ledger()

    async def session_stats(self, session_ids: list[str] | None) -> tuple[SessionStatsInfo, ...]:
        """Return the stored totals of some sessions, or of the current one."""
        return await self.client.session_stats(session_ids)

    def self_compaction(self) -> tuple[bool | None, bool]:
        """Return the session's own choice and whether self-compaction is in force."""
        return self.client.self_compaction_choice, self.client.self_compaction

    async def use_self_compaction(self, choice: bool | None) -> bool:
        """Save the session's choice; the write runs off the event loop."""
        return await asyncio.to_thread(self.client.use_self_compaction, choice)

    async def check_models(self, timeout: float) -> tuple[ModelCheck, ...]:
        """Ask every configured model one short question."""
        return await self.client.check_models(timeout=timeout)


def result_payload(result: RunResult) -> dict[str, object]:
    """Return a finished run as JSON: its answer, its usage and its tool calls."""
    return result_out(result).model_dump(mode="json")
