"""The agent a server process owns: who may run, and how a run's events reach a client.

A server serves one workspace. The conversation a prompt continues is the *current* one, and one run goes at a time
in it: a prompt that arrives while another runs there is refused with ``busy`` instead of queued, so the caller can see
that nothing happened and a long run is never silently joined by a second.

A run does not stop being there when the reader looks at something else. Opening or starting another session while the
current one is running puts the running one aside as a *slot* of its own — its own SDK client, run, lock, pending answer
and inbox — and goes on in a new one; opening the running session again brings its slot back. A slot that is not the
current one and has nothing running is closed, because everything it held is stored.

A run started over HTTP has no terminal to answer it, so the answers travel with the request or over the endpoints
that post back into the run: :class:`~zettcode.server.schemas.ApprovalPolicy` decides shell commands up front
(``deny``, ``auto``, ``commands``) or defers each one to the client (``ask``); questions are declined unless the
request says ``questions: ask``. A deferred approval waits for ``POST /runs/approvals`` for ``answer_timeout``
seconds and then takes the safe default, so a client that went away cannot leave a command suspended. A question has
no deadline: it waits for ``POST /runs/questions`` as long as the reader takes, and the run can still be cancelled.
"""

from __future__ import annotations

import asyncio
import base64
import inspect
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, cast

from zettcode.sdk.errors import SessionBusyError
from zettcode.sdk.events import ApprovalRequested, QuestionAsked
from zettcode.sdk.handlers import ApprovalHandler, approve_all, approve_commands, deny_all
from zettcode.sdk.types import Receipt

from .schemas import ApprovalPolicy, PendingOut, PromptRequest, ResumeRequest, SteerIn
from .serialize import event_payload, result_out

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zettcode.sdk.client import Client, RunStream
    from zettcode.sdk.session import Session
    from zettcode.sdk.types import (
        Image,
        IncomingMessage,
        MentionInfo,
        ModelCheck,
        ModelInfo,
        ResumeInfo,
        RunResult,
        SessionStatsInfo,
        WorkspaceUsage,
    )

    from .schemas import CommandOut
    from .settings import Settings

#: What a run may be asked to do, whether it starts a prompt or continues one.
Request = PromptRequest | ResumeRequest

#: Builds the client the server runs on; the tests pass one that answers without a model.
ClientFactory = Callable[[], "Client"]

#: One frame of a run: its SSE event name, and the JSON payload under it.
Frame = tuple[str, dict[str, object]]

#: Messages another session may leave waiting for this chat; beyond it the sender is refused, as in the terminal.
MAX_INBOX = 16


@dataclass(frozen=True, slots=True)
class Waiting:
    """A message another session sent, waiting for this chat to answer it."""

    id: str
    message: IncomingMessage


@dataclass(eq=False)
class Slot:
    """One open conversation: the client that holds it, and what is going on in it.

    Attributes:
        client: The SDK client, which holds one conversation at a time and one run at a time.
        lock: Held for as long as a run, a resumed request or a side question is going.
        run: The run in progress, so it can be stopped.
        pending: The approval or question the run is suspended on.
        messages: What other sessions sent here that has not been answered yet.
    """

    client: Client
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    run: RunStream | None = None
    pending: Pending | None = None
    messages: list[Waiting] = field(default_factory=list)

    @property
    def session_id(self) -> str:
        """Return the conversation this slot holds now."""
        return self.client.session.id

    @property
    def busy(self) -> bool:
        """Return whether something is running here."""
        return self.lock.locked()


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


def images_of(request: Request | SteerIn) -> tuple[Image, ...]:
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
                work_dir=self.event.work_dir,
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


class NoModelError(RuntimeError):
    """No model is configured yet, so there is nothing to run a prompt with.

    A fresh machine has no ``[[models]]`` entry; the server still starts, lists and edits the configuration, and
    answers this on what needs an agent. ``POST /models`` is what turns it into a working server.
    """


class Runner:
    """The agent, one run at a time, and the events and answers of the run that is going.

    The client is optional: a workspace with no configured model has none, and the server still serves the
    configuration endpoints so one can be set up from the editor that is using it. Everything that needs the agent
    raises :class:`NoModelError`, which the API maps to ``409 no_model``.

    Args:
        settings: The workspace and the level a run starts at.
        factory: Builds the client; by default an SDK :class:`~zettcode.sdk.Client` on the settings' workspace.
            ``None`` from it means "no model configured", which is how the tests cover the setup path.
    """

    def __init__(self, settings: Settings, factory: ClientFactory | None = None) -> None:
        self.settings = settings
        self._factory = factory
        #: The conversation a prompt continues, and what is going on in it; ``None`` before a model is configured.
        self._slot: Slot | None = None
        #: Conversations put aside while they run, so the reader can look at another one meanwhile.
        self._aside: list[Slot] = []
        self._sequence = 0

    # -- the slots ------------------------------------------------------------
    @property
    def _client(self) -> Client | None:
        return None if self._slot is None else self._slot.client

    @_client.setter
    def _client(self, client: Client | None) -> None:
        # Only ever set while nothing runs: a first start, a reload, a test that takes the client away.
        self._slot = None if client is None else Slot(client)

    @property
    def slot(self) -> Slot:
        """Return the current conversation's slot.

        Raises:
            NoModelError: No model is configured yet, so there is no agent to drive.
        """
        if self._slot is None:
            raise NoModelError("No model is configured; add one with POST /models")
        return self._slot

    @property
    def slots(self) -> tuple[Slot, ...]:
        """Return every open conversation: the current one first, then the ones running aside."""
        return (*([self._slot] if self._slot is not None else []), *self._aside)

    def running_sessions(self) -> frozenset[str]:
        """Return the ids of the conversations something is running in, the current one included."""
        return frozenset(slot.session_id for slot in self.slots if slot.busy)

    # -- life -----------------------------------------------------------------
    async def start(self) -> None:
        """Open the client, or start without one when no model is configured yet.

        The SDK refuses a configuration with no models, and that is the state of every fresh machine. Rather than
        refuse to serve, the server keeps the configuration endpoints open and answers what needs a model with
        ``no_model``.
        """
        if self._client is not None:
            return
        if self._factory is not None:
            self._client = self._factory()
            return
        from zettcode.sdk import Client
        from zettcode.sdk.errors import ConfigurationError

        try:
            self._client = await asyncio.to_thread(
                lambda: Client(
                    self.settings.workspace,
                    config_path=self.settings.config_path,
                    model=self.settings.model,
                    effort=self.settings.effort,
                    permission=self.settings.permission,
                    jit_harness=self.settings.harness,
                    sessions_enabled=True,
                )
            )
        except ConfigurationError as error:
            if "No models configured" not in str(error):
                raise
            self._client = None
        else:
            await self._join(self.slot)

    @property
    def ready(self) -> bool:
        """Return whether a model is configured, so a prompt can run."""
        return self._client is not None

    async def close(self) -> None:
        """Stop everything still running and close every client, which releases the session locks."""
        slots, self._slot, self._aside = self.slots, None, []
        for slot in slots:
            run = slot.run
            if run is not None:
                await run.aclose()
        for slot in slots:
            await slot.client.aclose()

    @property
    def client(self) -> Client:
        """Return the open client of the current conversation.

        Raises:
            NoModelError: No model is configured yet, so there is no agent to drive.
        """
        return self.slot.client

    @property
    def maybe_client(self) -> Client | None:
        """Return the client, or ``None`` before a model is configured."""
        return self._client

    @property
    def busy(self) -> bool:
        """Return whether a prompt is running in the current conversation."""
        return self._slot is not None and self._slot.busy

    @property
    def pending(self) -> PendingOut | None:
        """Return the approval or question the current run waits on, if it is waiting on one."""
        slot = self._slot
        return None if slot is None or slot.pending is None else slot.pending.describe()

    # -- running --------------------------------------------------------------
    async def stream(self, request: Request, *, resume: bool = False) -> AsyncIterator[Frame]:
        """Run one prompt, or continue an interrupted one, and yield its events and then its result.

        The stream ends with ``result`` when the model finished, ``error`` when the run failed, and ``cancelled`` when
        it was stopped from outside — a closed connection included, which is what stops a run whose reader is gone.
        The run belongs to the conversation that was current when it began and goes on there, whichever one is
        current later.
        """
        slot = self.slot
        if slot.busy:
            raise SessionBusyError("A run is already in progress; wait for it or cancel it")
        handler = approval_handler(request.approvals)
        images = images_of(request)
        async for frame in self._drive(slot, lambda: self._start(slot, request, handler, images, resume), request):
            yield frame

    def commands(self) -> list[dict[str, object]]:
        """Return every command the plugins registered for all front ends, as the endpoint lists them."""
        return [
            {
                "name": command.name,
                "summary": command.summary,
                "when_busy": command.when_busy,
                "subcommands": [getattr(word, "name", str(word)) for word in command.subcommands],
            }
            for command in self.client.plugins.plain_commands
        ]

    async def run_command(self, name: str, argument: str) -> CommandOut:
        """Run one of those commands and return what it answered with.

        The level it is handed is the session's own, so a command that asks the model for something decides in the
        same terms the terminal's does.

        Raises:
            KeyError: No plugin registered that name.
        """
        from ..sdk.commands import PlainCommandContext, TextCommandResult, TurnCommandResult

        wanted = name if name.startswith("/") else f"/{name}"
        commands = list(self.client.plugins.plain_commands)
        command = next((item for item in commands if item.name == wanted), None)
        if command is None:
            raise KeyError(wanted)
        result = command.handler(PlainCommandContext(argument=argument, level=self.client.permission))
        if inspect.isawaitable(result):
            result = await result
        if isinstance(result, TurnCommandResult):
            return CommandOut(notification=result.notification, prompt=result.prompt, shown=result.shown)
        if isinstance(result, TextCommandResult):
            return CommandOut(message=result.message, notification=result.notification)
        raise TypeError(f"{wanted} answered with {type(result).__name__}")

    def stream_message(self, message_id: str) -> AsyncIterator[Frame]:
        """Answer one message another session sent, in the frames a prompt's stream uses.

        The turn is the terminal's: the message is what the model reads, framed with where it came from, and the
        answer belongs to this chat's own reader. The sender hears back only if the model sends it something with
        ``send_message``.

        Raises:
            KeyError: No such message is waiting; it was answered, or never arrived.
            SessionBusyError: A run is already in progress.
        """
        slot = self.slot
        if slot.busy:
            raise SessionBusyError("A run is already in progress; wait for it or cancel it")
        waiting = self._take(slot, message_id)
        return self._drive(slot, lambda: slot.client.relay(waiting.message))

    def _take(self, slot: Slot, message_id: str) -> Waiting:
        """Remove and return a waiting message.

        Raises:
            KeyError: Nothing with that id is waiting.
        """
        for index, waiting in enumerate(slot.messages):
            if waiting.id == message_id:
                return slot.messages.pop(index)
        raise KeyError(message_id)

    def ask_stream(self, question: str, timeout: float | None) -> AsyncIterator[Frame]:
        """Answer a side question and yield the answer as it is written, in the frames a prompt uses.

        The question holds the run lock while it is answered, so a prompt cannot start under it and
        ``/runs/cancel`` stops it like any other run; it ends in ``result``, ``error`` or ``cancelled``.
        """
        slot = self.slot
        if slot.busy:
            raise SessionBusyError("A run is already in progress; ask again when it ends")
        return self._drive(slot, lambda: slot.client.session.ask_stream(question, timeout=timeout))

    async def _drive(
        self, slot: Slot, start: Callable[[], RunStream], request: Request | None = None
    ) -> AsyncIterator[Frame]:
        """Hold a slot's lock for the length of one run and yield its frames.

        Args:
            slot: The conversation the run belongs to; it keeps the lock, the run and any pending answer, so a run
                that is no longer the one the reader looks at is neither lost nor mixed up with the one that is.
            start: Makes the SDK's run; called with the lock held, so a failure to start releases it.
            request: The request, when it may ask the client to answer approvals and questions.
        """
        await slot.lock.acquire()
        try:
            run = start()
            slot.run = run
            async for event in run:
                yield "event", event_payload(event)
                if request is not None:
                    note = await self._settle(slot, event, request)
                    if note:
                        yield "event", {"type": "notice", "text": note, "level": "warn"}
            result = run.result
            if result is None:
                yield "cancelled", {"type": "cancelled"}
            else:
                yield "result", result_payload(result)
        finally:
            slot.pending = None
            current, slot.run = slot.run, None
            try:
                if current is not None:
                    await current.aclose()
            finally:
                slot.lock.release()
            await self._tidy()

    def _start(
        self, slot: Slot, request: Request, handler: ApprovalHandler | None, images: tuple[Image, ...], resume: bool
    ) -> RunStream:
        """Start the SDK's run; kept apart so a failure to start does not look like a failure mid-stream."""
        client = slot.client
        if resume:
            return client.session.resume_stream(
                on_approval=handler, timeout=request.timeout, keep_events=request.keep_events
            )
        prompt = cast(PromptRequest, request)
        return client.prompt(
            prompt.text,
            images=images,
            mentions=prompt.mentions,
            instructions=prompt.instructions,
            on_approval=handler,
            timeout=request.timeout,
            keep_events=request.keep_events,
        )

    async def _settle(self, slot: Slot, event: object, request: Request) -> str | None:
        """Wait for the client's answer when the request asked for one; return a note when none came.

        Called after the event has gone down the stream and before the next one is asked for, which is exactly the
        window in which the SDK leaves a request unanswered and has not yet applied its own default.
        """
        if isinstance(event, ApprovalRequested) and request.approvals.mode == "ask":
            note = await self._hold(slot, Pending("approval", event.call_id, event), request.answer_timeout)
            if note and not event.answered:
                event.deny()
            return note
        if isinstance(event, QuestionAsked) and request.questions == "ask":
            # A question waits for the reader, not for a clock: a decline guessed on their behalf would end the
            # one thing the model asked them. Closing the stream still cancels the run.
            return await self._hold(slot, Pending("question", event.call_id, event), None)
        return None

    async def _hold(self, slot: Slot, pending: Pending, seconds: float | None) -> str | None:
        """Publish a pending request and wait for its answer; return why it gave up, or ``None``.

        An approval passes a deadline so a client that vanished cannot leave a command suspended forever. A
        question passes ``None`` and waits until it is answered or the run is cancelled.
        """
        slot.pending = pending
        try:
            if seconds is None:
                await pending.answered.wait()
                return None
            try:
                await asyncio.wait_for(pending.answered.wait(), seconds)
                return None
            except asyncio.TimeoutError:
                return f"No answer within {seconds:g}s; the command was denied."
        finally:
            slot.pending = None

    async def resolve_approval(self, call_id: str, approve: bool, remember: bool = False) -> bool:
        """Answer the approval the current run waits on; ``False`` when it names one that is not waiting."""
        pending = None if self._slot is None else self._slot.pending
        if pending is None or pending.kind != "approval" or pending.call_id != call_id:
            return False
        event = cast(ApprovalRequested, pending.event)
        if event.answered:
            return False
        event.approve(remember=remember) if approve else event.deny()
        pending.answered.set()
        return True

    async def resolve_question(self, call_id: str, answer: str | None) -> bool:
        """Answer, or decline with ``None``, the question the current run waits on."""
        pending = None if self._slot is None else self._slot.pending
        if pending is None or pending.kind != "question" or pending.call_id != call_id:
            return False
        event = cast(QuestionAsked, pending.event)
        if event.answered:
            return False
        event.answer(answer) if answer is not None else event.decline()
        pending.answered.set()
        return True

    async def cancel(self) -> bool:
        """Stop the run in progress in the current conversation, if there is one, and return whether there was.

        The stream of a cancelled run sees its events end and reports ``cancelled``; its reader is not an error.
        """
        run = None if self._slot is None else self._slot.run
        if run is None:
            return False
        await run.aclose()
        return True

    # -- looking at another conversation -------------------------------------
    async def open_session(self, session_id: str) -> Session:
        """Make a stored conversation the current one, whatever the current one is doing.

        Idle, the client simply moves to it. Running, the client stays with its run and a new one takes the reader to
        the other conversation; and a conversation that is running aside is brought back as it is, run and all.

        Raises:
            SessionNotFoundError: No such session is stored.
            SessionLockedError: Another process has it open.
        """
        slot = self.slot
        if slot.session_id == session_id:
            return slot.client.session
        aside = next((other for other in self._aside if other.session_id == session_id), None)
        if aside is not None:
            await self._make_current(aside)
            return aside.client.session
        if not slot.busy:
            return await slot.client.sessions.open(session_id)
        fresh = await self._spawn(slot.client)
        try:
            session = await fresh.client.sessions.open(session_id)
        except BaseException:
            await fresh.client.aclose()
            raise
        await self._make_current(fresh)
        return session

    async def new_session(self) -> Session:
        """Start an empty conversation and make it the current one, leaving a run in the old one to go on."""
        slot = self.slot
        if not slot.busy:
            return slot.client.sessions.new()
        fresh = await self._spawn(slot.client)
        await self._make_current(fresh)
        return fresh.client.session

    async def _make_current(self, slot: Slot) -> None:
        """Look at ``slot``: what was current is put aside while it runs, and closed when it does not."""
        previous = self._slot
        if slot in self._aside:
            self._aside.remove(slot)
        self._slot = slot
        if previous is not None and previous is not slot:
            self._aside.append(previous)
        await self._tidy()

    async def _tidy(self) -> None:
        """Close the conversations that are neither the current one nor running: all they held is stored."""
        for slot in list(self._aside):
            if slot is self._slot or slot.busy:
                continue
            self._aside.remove(slot)
            await slot.client.aclose()

    async def _spawn(self, like: Client) -> Slot:
        """Open another client that works the way ``like`` does: the same model, effort, permission and harness."""
        client = await self._open_client(
            model=like.model.name, effort=like.effort, permission=like.permission, harness=like.harness
        )
        if client is None:
            raise NoModelError("No model is configured; add one with POST /models")
        slot = Slot(client)
        await self._join(slot)
        return slot

    # -- the conversation, without running it --------------------------------
    def steer(self, message: str, request: SteerIn | None = None) -> str | None:
        """Send a message into the run in progress; the text the run reports it by, or ``None`` when nothing took it.

        ``request`` carries the pictures and the ``mentions`` switch, as a prompt's does.
        """
        images = images_of(request) if request is not None else ()
        mentions = bool(getattr(request, "mentions", False))
        return self.client.session.steer(message, images=images, mentions=mentions)

    async def resumable(self) -> ResumeInfo | None:
        """Return where the conversation was interrupted, or ``None`` when it was not."""
        return await self.client.session.resumable()

    # -- the models the config file lists ------------------------------------
    def models_now(self) -> tuple[ModelInfo, ...]:
        """Return the configured models, from the client when there is one and from the file when there is not."""
        if self._client is not None:
            return tuple(self._client.models)
        from zettcode.sdk import list_models

        return list_models(self.settings.config_path)

    @property
    def current_model(self) -> str | None:
        """Return the model a run would use, or ``None`` before one is configured."""
        return None if self._client is None else self._client.model.name

    async def reload(self, *, model: str | None = None) -> None:
        """Rebuild the client after the configuration file changed, keeping the conversation and its settings.

        The SDK reads the models when a client is made, so a model added, changed or removed on disk reaches the agent
        by making the client again. The session id is carried over (a fresh, never-stored one simply starts again), as
        are the effort, permission and harness, and the model named stays if it is still configured.

                Raises:
                    SessionBusyError: A run is in progress; the configuration of a running conversation is not swapped.
        """
        if self.busy:
            raise SessionBusyError("A run is in progress; change the models when it ends")
        previous = self._client
        session = previous.session.id if previous is not None else None
        permission = previous.permission if previous is not None else self.settings.permission
        harness = previous.harness if previous is not None else self.settings.harness
        effort = previous.effort if previous is not None else self.settings.effort
        wanted = model or (previous.model.name if previous is not None else None)
        if previous is not None:
            await previous.aclose()
        self._client = None
        if self._factory is not None:
            self._client = self._factory()
            if self._client is not None and model is not None:
                self._client.use_model(model)
            return

        from zettcode.sdk.errors import SessionNotFoundError

        async def open_client(resume: str | None) -> Client | None:
            return await self._open_client(
                model=wanted, effort=effort, permission=permission, harness=harness, resume=resume
            )

        if previous is not None:
            await previous.aclose()
        self._slot = None
        try:
            client = await open_client(session)
        except SessionNotFoundError:
            client = await open_client(None)
        if client is None:
            return
        if self._factory is not None and model is not None:
            client.use_model(model)
        self._slot = Slot(client)
        await self._join(self._slot)

    async def _open_client(
        self, *, model: str | None, effort: str | None, permission: str, harness: bool, resume: str | None = None
    ) -> Client | None:
        """Make a client for this workspace that works the way the arguments say; ``None`` when no model is configured."""
        if self._factory is not None:
            return self._factory()
        from zettcode.sdk import Client, list_models

        models = list_models(self.settings.config_path)
        if not models:
            return None
        chosen = model if model in {entry.name for entry in models} else None
        return await asyncio.to_thread(
            lambda: Client(
                self.settings.workspace,
                config_path=self.settings.config_path,
                model=chosen,
                effort=effort,
                permission=permission,
                jit_harness=harness,
                resume=resume,
                sessions_enabled=True,
            )
        )

    async def _join(self, slot: Slot) -> None:
        """Become a session the others can address, so a message sent to this conversation arrives here."""
        if self._factory is not None:
            return  # a stand-in client has no line to the broker
        await slot.client.join_sessions(lambda message: self._received(slot, message))

    def received(self, message: IncomingMessage) -> Receipt:
        """Take a message another session sent to the current conversation; see :meth:`_received`."""
        return self._received(self.slot, message)

    def _received(self, slot: Slot, message: IncomingMessage) -> Receipt:
        """Hold a message another session sent to ``slot``; the chat answers it when its next poll asks for one.

        Called by the SDK on the event loop with the sender waiting for the answer, so it must not block. Holding
        the message rather than starting a run here is what lets the editor draw the turn as one of its own, with
        the sender's name on it and the same stream a prompt uses.
        """
        if len(slot.messages) >= MAX_INBOX:
            return Receipt(False, f"this chat already has {len(slot.messages)} messages waiting")
        self._sequence += 1
        slot.messages.append(Waiting(f"message-{self._sequence}", message))
        return Receipt(True, disposition="queued")

    def waiting(self) -> tuple[Waiting, ...]:
        """Return the messages the current conversation has not answered yet, oldest first."""
        return () if self._slot is None else tuple(self._slot.messages)

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

    async def send(self, to: str, text: str) -> tuple[str, str]:
        """Send a message to another session; return the handle that took it and what it will do with it."""
        delivered = await self.client.send(to, text)
        return delivered.to, delivered.disposition


def result_payload(result: RunResult) -> dict[str, object]:
    """Return a finished run as JSON: its answer, its usage and its tool calls."""
    return result_out(result).model_dump(mode="json")
