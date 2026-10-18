"""A stand-in for the SDK's client: the API is tested without a model, a provider, or a directory.

The doubles answer with the SDK's own value types (:class:`~zettcode.sdk.types.Usage`,
:class:`~zettcode.sdk.events.TextDelta`, ...), so what the server serializes in a test is what it serializes in
production. What they replace is the model call and the store: a run replays a prepared list of events, and the
session registry is a list in memory. A run also applies the approval handler to each request, as the SDK's run does
before it yields the event.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncIterator, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from zettcode.sdk.errors import SessionNotFoundError
from zettcode.sdk.events import AnyEvent, TextDelta
from zettcode.sdk.types import (
    Compaction,
    ContextReport,
    ContextShare,
    Message,
    ModelInfo,
    RunResult,
    SessionInfo,
    Usage,
)

WHEN = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)


class FakeRun:
    """One run: replays events, may raise, and can be closed from outside as a cancel would."""

    def __init__(
        self,
        events: Sequence[AnyEvent] = (),
        *,
        result: RunResult | None = None,
        error: BaseException | None = None,
        hold: asyncio.Event | None = None,
    ) -> None:
        self.events = list(events)
        self._result = result
        self.error = error
        self.hold = hold
        self.closed = False
        self.result: RunResult | None = None
        #: Set by the client when the run starts: the rule the request answered approvals with.
        self.on_approval: object | None = None

    def __aiter__(self) -> AsyncIterator[AnyEvent]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[AnyEvent]:
        for event in self.events:
            if self.closed:
                return
            await self._apply(event)
            yield event
        if self.hold is not None:
            await self.hold.wait()
        if self.error is not None:
            raise self.error
        if self.closed:
            return
        self.result = self._result or RunResult(text="done", session_id="session-1")

    async def _apply(self, event: AnyEvent) -> None:
        """Answer what the SDK's run answers before yielding: an approval, by the request's rule."""
        from zettcode.sdk.events import ApprovalRequested, QuestionAsked, _Reply

        if isinstance(event, (ApprovalRequested, QuestionAsked)) and not event.answered:
            # A real reply slot, so an endpoint can answer through the SDK's own methods.
            object.__setattr__(event, "_reply", _Reply(lambda outcome: None))
        if not isinstance(event, ApprovalRequested) or self.on_approval is None:
            return
        if not event.answered:
            object.__setattr__(event, "_reply", _Reply(lambda outcome: None))
        outcome = self.on_approval(event)  # type: ignore[operator]
        if inspect.isawaitable(outcome):
            outcome = await outcome
        if outcome is not None and not event.answered:
            event.approve() if outcome else event.deny()

    async def aclose(self) -> None:
        self.closed = True
        if self.hold is not None:
            self.hold.set()


class FakeSession:
    """One conversation, with the parts of the SDK's session the endpoints touch."""

    def __init__(self, name: str = "session-1", title: str | None = "A conversation") -> None:
        self.id = name
        self._title = title
        self.locked = False
        self.messages: list[Message] = [Message(role="user", text="hello")]
        self.compaction: Compaction | None = None
        self.report: ContextReport | None = ContextReport(
            window=200_000, used=1_000, measured_by="estimate", shares=(ContextShare("System", 500, 2),)
        )
        self.usage = Usage(input_tokens=10, output_tokens=2, requests=1)
        self.asked_side: list[str] = []
        self.steered: list[str] = []
        self.steering = True
        self.resume_info: object | None = None
        self.resume_options: dict[str, object] = {}
        self.named = 0

    @property
    def title(self) -> str | None:
        return self._title

    async def rename(self, title: str) -> str:
        self._title = title
        return title

    async def name_it(self) -> str | None:
        self.named += 1
        self._title = "Named by the model"
        return self._title

    async def export(self, path: object = None) -> Path:
        target = Path(str(path)) if path is not None else Path("zettcode-export.html")
        target.write_text("<html>the conversation</html>", encoding="utf-8")
        return target

    async def ask(self, question: str, *, timeout: float | None = None) -> str:
        self.asked_side.append(question)
        return f"about {question}"

    def steer(self, message: str) -> bool:
        self.steered.append(message)
        return self.steering

    async def resumable(self) -> object | None:
        return self.resume_info

    def resume_stream(self, **options: object) -> FakeRun:
        self.resume_options = options
        return FakeRun([TextDelta("session-1", "resumed")], result=RunResult(text="resumed", session_id="session-1"))

    async def fork(self) -> FakeSession:
        return FakeSession("session-fork", self._title)

    async def compact(self) -> Compaction | None:
        return self.compaction

    async def context(self) -> ContextReport | None:
        return self.report

    async def history(self) -> list[Message]:
        return list(self.messages)


class FakeSessions:
    """The registry: a list in memory, with the SDK's four operations."""

    def __init__(self, client: FakeClient) -> None:
        self.client = client
        self.stored = [
            SessionInfo("session-1", "A conversation", WHEN, WHEN),
            SessionInfo("session-2", "Another one", WHEN, WHEN),
        ]

    async def list(self, *, limit: int = 20) -> list[SessionInfo]:
        return self.stored[:limit]

    def new(self) -> FakeSession:
        self.client.session = FakeSession("session-new", None)
        self.stored.insert(0, SessionInfo("session-new", None, WHEN, WHEN))
        return self.client.session

    async def open(self, session_id: str) -> FakeSession:
        if not any(item.id == session_id for item in self.stored):
            raise SessionNotFoundError(f"No session {session_id!r} in this workspace")
        self.client.session = FakeSession(session_id, "A conversation")
        return self.client.session


class FakeClient:
    """The client the endpoints talk to: models, settings, usage, sessions and one prepared run per prompt."""

    def __init__(self, *, runs: Sequence[FakeRun] = (), token: str = "") -> None:
        self.workspace = None
        self.models = (
            ModelInfo("gpt-5", "gpt-5", 400_000, True, ("low", "medium", "high"), active=True),
            ModelInfo("fast", "gpt-5-mini", 200_000, False, ("low", "medium")),
        )
        self.model = self.models[0]
        self.effort = "medium"
        self.efforts = ("low", "medium", "high")
        self.permission = "deny"
        self.permissions = ("deny", "ask", "safe", "auto")
        self.usage = Usage(input_tokens=100, output_tokens=20, requests=2)
        self.session = FakeSession()
        self.sessions = FakeSessions(self)
        self.runs = list(runs)
        self.asked: list[str] = []
        self.approvals: list[Any] = []
        self.prompt_options: list[dict[str, object]] = []
        self.closed = False

    @property
    def plugins(self) -> object:
        from zettcode.sdk.client import PluginReport

        return PluginReport(("shell", "usage"), ("broken: no such module",))

    def use_model(self, name: str) -> ModelInfo:
        for model in self.models:
            if model.name == name:
                self.model = ModelInfo(
                    model.name, model.model, model.context_window, model.multimodal, model.efforts, active=True
                )
                return self.model
        raise ValueError(f"No model called {name!r}")

    def use_effort(self, name: str) -> str:
        if name not in self.efforts:
            raise ValueError(f"Unknown effort {name!r}")
        self.effort = name
        return name

    def use_permission(self, name: str) -> str:
        if name not in self.permissions:
            raise ValueError(f"Unknown permission {name!r}")
        self.permission = name
        return name

    def prompt(self, text: str, **options: object) -> FakeRun:
        self.asked.append(text)
        self.approvals.append(options.get("on_approval"))
        self.prompt_options.append(dict(options))
        run = self.runs.pop(0) if self.runs else FakeRun([TextDelta("session-1", "hi")])
        run.on_approval = options.get("on_approval")
        return run

    async def aclose(self) -> None:
        self.closed = True
