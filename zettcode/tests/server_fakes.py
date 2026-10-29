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
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from zettcode.sdk.errors import SessionNotFoundError
from zettcode.sdk.events import AnyEvent, TextDelta
from zettcode.sdk.types import (
    Compaction,
    ContextReport,
    ContextShare,
    DayTotals,
    MentionInfo,
    Message,
    ModelCheck,
    ModelInfo,
    ModelTotals,
    RunResult,
    SessionInfo,
    SessionStatsInfo,
    SessionTotals,
    Totals,
    Usage,
    WorkspaceUsage,
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

    #: What the next streamed side question does; a test sets it to hold the answer open.
    side_hold: asyncio.Event | None = None

    def ask_stream(self, question: str, *, timeout: float | None = None) -> FakeRun:
        self.asked_side.append(question)
        return FakeRun(
            [TextDelta(self.id, "about "), TextDelta(self.id, question)],
            result=RunResult(text=f"about {question}", session_id=self.id),
            hold=self.side_hold,
        )

    def steer(self, message: str, *, images: object = (), mentions: bool = False) -> str | None:
        self.steered.append(message)
        self.steer_options = {"images": tuple(images), "mentions": mentions}  # type: ignore[call-overload]
        return message if self.steering else None

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

    async def history(self, *, full: bool = False) -> list[Message]:
        if full:
            return [*self.messages, Message(role="summary", text="an older summary")]
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
        self.permissions = ("deny", "ask", "safe", "full")
        self.harness = False
        self.usage = Usage(input_tokens=100, output_tokens=20, requests=2)
        self.session = FakeSession()
        self.sessions = FakeSessions(self)
        self.runs = list(runs)
        self.asked: list[str] = []
        self.relayed: list[Any] = []
        self.sent: list[tuple[str, str]] = []
        self.approvals: list[Any] = []
        self.prompt_options: list[dict[str, object]] = []
        self.self_choice: bool | None = None
        self.effective_self_compaction = False
        self.checks: list[ModelCheck] = [
            ModelCheck("gpt-5", "gpt-5", True, 0.4, "ok", 5, 1),
            ModelCheck("fast", "gpt-5-mini", False, 2.0, "401 Unauthorized"),
        ]
        self.doctor_timeout: float | None = None
        self.unwritten: str | None = None
        self.closed = False
        self.switched: list[tuple[str, bool]] = []

    @property
    def plugins(self) -> object:
        from zettcode.sdk.client import PluginReport
        from zettcode.sdk.types import PluginEntry

        return PluginReport(
            ("shell", "usage"),
            ("broken: no such module",),
            entries=(
                PluginEntry("shell", "shell", builtin=True),
                PluginEntry("usage", "usage", builtin=True),
                PluginEntry("acme", "zettcode-acme"),
                PluginEntry("quiet", "zettcode-quiet", enabled=False),
                PluginEntry("broken", "broken", failure="no such module"),
            ),
        )

    def set_plugin_enabled(self, name: str, enabled: bool) -> object:
        from zettcode.sdk.types import PluginEntry

        if name in ("shell", "usage"):
            raise ValueError(f"{name} is compiled into the program, so it cannot be switched off")
        if name not in ("zettcode-acme", "zettcode-quiet"):
            raise ValueError(f"No plugin is called {name!r}")
        self.switched.append((name, enabled))
        return PluginEntry(name, name, enabled=enabled)

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
        name = "full" if name == "auto" else name  # the SDK takes the old name of `full` and answers with the new
        if name not in self.permissions:
            raise ValueError(f"Unknown permission {name!r}")
        self.permission = name
        return name

    def use_harness(self, on: bool) -> bool:
        self.harness = bool(on)
        return self.harness

    def use_compact_percent(self, percent: float) -> tuple[ModelInfo, str | None]:
        if not 0 < percent <= 100:
            raise ValueError("The compression share must be more than 0 and at most 100.")
        self.model = ModelInfo(
            self.model.name,
            self.model.model,
            self.model.context_window,
            self.model.multimodal,
            self.model.efforts,
            active=True,
            compact_percent=percent,
        )
        self.models = tuple(self.model if item.name == self.model.name else item for item in self.models)
        return self.model, self.unwritten

    def prompt(self, text: str, **options: object) -> FakeRun:
        self.asked.append(text)
        self.approvals.append(options.get("on_approval"))
        self.prompt_options.append(dict(options))
        run = self.runs.pop(0) if self.runs else FakeRun([TextDelta("session-1", "hi")])
        run.on_approval = options.get("on_approval")
        return run

    async def send(self, to: str, text: str) -> Any:
        from zettcode.sdk.errors import SendError
        from zettcode.sdk.types import Delivered

        self.sent.append((to, text))
        if to == "nobody":
            raise SendError("not_found", "no session is called @nobody")
        return Delivered(to, "started")

    def relay(self, message: object, **options: object) -> FakeRun:
        self.relayed.append(message)
        run = self.runs.pop(0) if self.runs else FakeRun([TextDelta("session-1", "hi")])
        run.on_approval = options.get("on_approval")
        return run

    async def aclose(self) -> None:
        self.closed = True

    # -- what a terminal shows around the conversation -----------------------
    def mentions(self, query: str = "", *, limit: int = 50) -> tuple[MentionInfo, ...]:
        found = (
            MentionInfo("@src/cli.py", "file", "src/cli.py", "4.2 KB"),
            MentionInfo("@code-review", "skill", "code-review", "Review a change"),
        )
        return tuple(item for item in found if query.lower() in item.name.lower())[:limit]

    async def usage_ledger(self) -> WorkspaceUsage:
        tokens = Totals(requests=3, input_tokens=1800, output_tokens=180, cache_read_tokens=700)
        return WorkspaceUsage(
            sessions=(SessionTotals("session-1", "A conversation", WHEN, WHEN, tokens, ("gpt-5",), entries=4),),
            models=(ModelTotals("gpt-5", tokens),),
            days=(DayTotals(date(2026, 10, 18), tokens),),
            total=tokens,
        )

    async def session_stats(self, session_ids: Sequence[str] | None = None) -> tuple[SessionStatsInfo, ...]:
        ids = list(session_ids) if session_ids is not None else [self.session.id]
        known = SessionStatsInfo(
            "session-1", entries=4, requests=2, input_tokens=1300, output_tokens=130, cache_read_tokens=600
        )
        return tuple(known if session_id == "session-1" else SessionStatsInfo(session_id) for session_id in ids)

    @property
    def self_compaction_choice(self) -> bool | None:
        return self.self_choice

    @property
    def self_compaction(self) -> bool:
        return self.effective_self_compaction if self.self_choice is None else self.self_choice

    def use_self_compaction(self, choice: bool | None) -> bool:
        self.self_choice = choice
        return self.self_compaction

    async def check_models(self, *, timeout: float = 30.0) -> tuple[ModelCheck, ...]:
        self.doctor_timeout = timeout
        return tuple(self.checks)
