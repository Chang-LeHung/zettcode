"""The FastAPI application: the endpoints, the error shapes, and the one run in progress.

Every endpoint is a thin move on the SDK. What this module owns is the contract: which status a failure becomes, what
a stream frame looks like, and that a second prompt while one runs is refused rather than queued.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import tempfile
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from zettcode.sdk.errors import (
    ConfigurationError,
    NothingToDoError,
    RunError,
    RunTimeoutError,
    SessionBusyError,
    SessionLockedError,
    SessionNotFoundError,
    ZettCodeError,
)
from zettcode.sdk.models import add_model as add_model_entry
from zettcode.sdk.models import remove_model as remove_model_entry
from zettcode.sdk.models import update_model as update_model_entry

from . import __version__
from .runner import NoModelError, Runner, prepare, result_payload
from .runner import Request as RunRequest
from .schemas import (
    AnswerOut,
    ApprovalAnswer,
    ApprovalPolicy,
    CancelledOut,
    CompactionOut,
    ContextOut,
    CurrentSessionOut,
    DoctorOut,
    DoctorRequest,
    ErrorOut,
    HealthOut,
    HistoryOut,
    MentionsOut,
    ModelCreate,
    ModelsOut,
    ModelUpdate,
    PluginsOut,
    PromptRequest,
    QuestionAnswer,
    RenameRequest,
    ResolvedOut,
    ResumableOut,
    ResumeRequest,
    RunStateOut,
    SelfCompactionOut,
    SelfCompactionUpdate,
    SessionCreate,
    SessionOut,
    SessionsOut,
    SessionStatsListOut,
    SessionStatsOut,
    SettingsOut,
    SettingsUpdate,
    SideQuestionRequest,
    SteeredOut,
    SteerIn,
    UsageOut,
    WorkspaceUsageOut,
)
from .serialize import (
    check_out,
    compaction_out,
    context_out,
    current_session_out,
    ledger_out,
    mention_out,
    message_out,
    model_out,
    session_out,
    stats_out,
    usage_out,
)
from .settings import Settings

#: Builds the client a server runs on; a test passes a stand-in that answers without a model.
ClientFactory = Callable[[], Any]

#: The exceptions that become a client error, and the code and status each one gets.
FAILURES: tuple[tuple[type[BaseException], int, str], ...] = (
    (SessionNotFoundError, 404, "not_found"),
    (SessionLockedError, 409, "locked"),
    (SessionBusyError, 409, "busy"),
    (NothingToDoError, 409, "nothing_to_do"),
    (NoModelError, 409, "no_model"),
    (ConfigurationError, 400, "invalid"),
    (RunTimeoutError, 504, "timeout"),
    (RunError, 502, "run"),
    (ZettCodeError, 500, "internal"),
    (ValueError, 400, "invalid"),
)


def failure_of(error: BaseException) -> tuple[int, str]:
    """Return the status and the error code for an exception raised by an endpoint."""
    for kind, status, code in FAILURES:
        if isinstance(error, kind):
            return status, code
    return 500, "internal"


def error_body(code: str, message: str) -> dict[str, str]:
    """Return the one shape a failure is written in."""
    return ErrorOut(error=code, message=message).model_dump()


def sse_frame(event: str, payload: Mapping[str, object]) -> bytes:
    """Return one server-sent event: its name, and its JSON on one ``data:`` line."""
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {body}\n\n".encode()


def stream_of(runner: Runner, request: RunRequest, *, resume: bool = False) -> StreamingResponse:
    """Start a run and return the SSE response; the checks that deserve a status code happen before it opens.

    A body that cannot run (a command the approval rule refuses to match, an image that is not base64) is refused with
    a 4xx here, while a status line is still possible. What fails once the stream is open becomes an ``error`` frame,
    because by then the 200 has gone out.
    """
    if runner.busy:
        raise SessionBusyError("A run is already in progress; wait for it or cancel it")
    if not runner.ready:
        raise NoModelError("No model is configured; add one with POST /models")
    prepare(request)

    async def frames() -> AsyncIterator[bytes]:
        try:
            async for name, payload in runner.stream(request, resume=resume):
                yield sse_frame(name, payload)
        except Exception as error:  # noqa: BLE001 - the status line is gone; the failure goes down the stream
            _, code = failure_of(error)
            yield sse_frame("error", error_body(code, str(error)))

    return StreamingResponse(
        frames(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


def runner_of(request: Request) -> Runner:
    """Return the runner the server's lifespan put on the application."""
    return request.app.state.runner


#: The runner, as the dependency of every endpoint that needs the agent. It is written at module level because
#: the endpoint signatures are strings (``from __future__ import annotations``) and FastAPI resolves them there.
RunnerDep = Annotated[Runner, Depends(runner_of)]


def create_app(settings: Settings, *, client_factory: ClientFactory | None = None) -> FastAPI:
    """Build the application for one workspace.

    Args:
        settings: The workspace, the socket it will be served on, the token and how a run starts.
        client_factory: Builds the client; the real SDK client on the workspace unless a test supplies one.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        runner = Runner(settings, client_factory)
        await runner.start()
        app.state.runner = runner
        try:
            yield
        finally:
            await runner.close()

    app = FastAPI(
        title="ZettCode server",
        version=__version__,
        summary="The ZettCode coding agent over HTTP: prompts streamed as they run, sessions, models, usage.",
        lifespan=lifespan,
    )
    app.state.settings = settings

    async def authorize(authorization: Annotated[str | None, Header()] = None) -> None:
        """Require the bearer token, when one was configured, on everything but ``/health``."""
        if settings.token is None:
            return
        scheme, _, given = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(given.strip(), settings.token):
            raise StarletteHTTPException(
                status_code=401, detail="A bearer token is required", headers={"WWW-Authenticate": "Bearer"}
            )

    protected = APIRouter(dependencies=[Depends(authorize)])

    @app.get("/", include_in_schema=False)
    async def index() -> dict[str, str]:
        """Say what this is and where the rest is, for a browser pointed at the port."""
        return {
            "name": "ZettCode server",
            "version": __version__,
            "docs": "/docs",
            "health": "/health",
        }

    @app.get("/health", response_model=HealthOut, tags=["health"])
    async def health(runner: RunnerDep) -> HealthOut:
        """Say that the server is up, whether it has a model to work with, and which session it serves."""
        client = runner.maybe_client
        models = client.models if client is not None else runner.models_now()
        return HealthOut(
            version=__version__,
            workspace=str(settings.workspace),
            ready=client is not None,
            session=None if client is None else client.session.id,
            models=len(models),
            busy=runner.busy,
        )

    @protected.get("/models", response_model=ModelsOut, tags=["models"])
    async def models(runner: RunnerDep) -> ModelsOut:
        """List the configured models and say which one the next prompt would use.

        This works before a model is configured: the list then comes from the configuration file, and ``current`` is
        null until one is added.
        """
        return ModelsOut(models=[model_out(model) for model in runner.models_now()], current=runner.current_model)

    @protected.post("/models", response_model=ModelsOut, status_code=201, tags=["models"])
    async def add_model(body: ModelCreate, runner: RunnerDep) -> ModelsOut:
        """Add a model to the configuration file, and use it when the server had none.

        The first model is what turns a fresh server into a working one: the client is built as soon as the file
        holds it. A model added while another is in use is available for ``PATCH /settings``, and the conversation
        carries on with the one it was using.
        """
        if runner.busy:
            raise SessionBusyError("A run is in progress; change the models when it ends")
        added = await asyncio.to_thread(add_model_entry, body.entry(), path=settings.config_path)
        if not runner.ready:
            await runner.reload(model=added[-1].name)
        return ModelsOut(models=[model_out(model) for model in runner.models_now()], current=runner.current_model)

    @protected.patch("/models/{name}", response_model=ModelsOut, tags=["models"])
    async def change_model(name: str, body: ModelUpdate, runner: RunnerDep) -> ModelsOut:
        """Change one model in the configuration file; the token is kept unless a new one is given."""
        if runner.busy:
            raise SessionBusyError("A run is in progress; change the models when it ends")
        changes = body.changes()
        if not changes:
            raise ValueError("Name at least one field to change")
        await asyncio.to_thread(update_model_entry, name, changes, path=settings.config_path)
        await runner.reload(model=runner.current_model)
        return ModelsOut(models=[model_out(model) for model in runner.models_now()], current=runner.current_model)

    @protected.delete("/models/{name}", response_model=ModelsOut, tags=["models"])
    async def delete_model(name: str, runner: RunnerDep) -> ModelsOut:
        """Remove one model from the configuration file; the last one cannot go, since a client needs one."""
        if runner.busy:
            raise SessionBusyError("A run is in progress; change the models when it ends")
        await asyncio.to_thread(remove_model_entry, name, path=settings.config_path)
        await runner.reload()
        return ModelsOut(models=[model_out(model) for model in runner.models_now()], current=runner.current_model)

    @protected.get("/settings", response_model=SettingsOut, tags=["models"])
    async def settings_out(runner: RunnerDep) -> SettingsOut:
        """Return the model, effort and permission a run starts with."""
        client = runner.client
        return SettingsOut(
            model=model_out(client.model),
            effort=client.effort,
            efforts=list(client.efforts),
            permission=client.permission,
            permissions=list(client.permissions),
        )

    @protected.patch("/settings", response_model=SettingsOut, tags=["models"])
    async def change_settings(update: SettingsUpdate, runner: RunnerDep) -> SettingsOut:
        """Change the model, the reasoning effort, the permission level or the compaction point for the prompts that follow."""
        if (
            update.model is None
            and update.effort is None
            and update.permission is None
            and update.compact_percent is None
        ):
            raise ValueError("Name at least one of model, effort, permission or compact_percent")
        client = runner.client
        if update.model is not None:
            client.use_model(update.model)
        if update.effort is not None:
            client.use_effort(update.effort)
        if update.permission is not None:
            client.use_permission(update.permission)
        unsaved: str | None = None
        if update.compact_percent is not None:
            if runner.busy:
                raise SessionBusyError("A run is in progress; move the compaction point when it ends")
            _, unsaved = await asyncio.to_thread(client.use_compact_percent, update.compact_percent)
        current = await settings_out(runner)
        return current.model_copy(update={"unsaved": unsaved}) if unsaved else current

    @protected.get("/sessions", response_model=SessionsOut, tags=["sessions"])
    async def list_sessions(runner: RunnerDep, limit: Annotated[int, Query(ge=1, le=200)] = 20) -> SessionsOut:
        """List the stored sessions of this workspace, most recently active first."""
        client = runner.client
        stored = await client.sessions.list(limit=limit)
        return SessionsOut(sessions=[session_out(item, client.session.id) for item in stored])

    @protected.post("/sessions", response_model=SessionOut, status_code=201, tags=["sessions"])
    async def new_session(runner: RunnerDep, body: SessionCreate | None = None) -> SessionOut:
        """Start an empty conversation and make it the one the next prompt continues."""
        client = runner.client
        session = client.sessions.new()
        if body is not None and body.title:
            await session.rename(body.title)
        return SessionOut(id=session.id, title=session.title, current=True)

    @protected.get("/sessions/current", response_model=CurrentSessionOut, tags=["sessions"])
    async def current_session(runner: RunnerDep) -> CurrentSessionOut:
        """Return the conversation the next prompt continues, and what it has spent."""
        return current_session_out(runner.client.session)

    @protected.post("/sessions/{session_id}/open", response_model=CurrentSessionOut, tags=["sessions"])
    async def open_session(session_id: str, runner: RunnerDep) -> CurrentSessionOut:
        """Continue a stored conversation: the next prompt goes to it."""
        session = await runner.client.sessions.open(session_id)
        return current_session_out(session)

    @protected.post("/sessions/current/rename", response_model=SessionOut, tags=["sessions"])
    async def rename_session(body: RenameRequest, runner: RunnerDep) -> SessionOut:
        """Name the current conversation."""
        session = runner.client.session
        title = await session.rename(body.title)
        return SessionOut(id=session.id, title=title, current=True)

    @protected.post("/sessions/current/fork", response_model=CurrentSessionOut, tags=["sessions"])
    async def fork_session(runner: RunnerDep) -> CurrentSessionOut:
        """Carry this conversation into a new session and continue there."""
        return current_session_out(await runner.client.session.fork())

    @protected.post("/sessions/current/compact", response_model=CompactionOut, tags=["sessions"])
    async def compact_session(runner: RunnerDep) -> CompactionOut:
        """Summarize the conversation now, instead of waiting for the window to fill."""
        return compaction_out(await runner.client.session.compact())

    @protected.get("/sessions/current/context", response_model=ContextOut | None, tags=["sessions"])
    async def context_of_session(runner: RunnerDep) -> ContextOut | None:
        """Return how full the context window is, or ``null`` before a request has been measured."""
        report = await runner.client.session.context()
        return None if report is None else context_out(report)

    @protected.get("/sessions/current/history", response_model=HistoryOut, tags=["sessions"])
    async def history_of_session(runner: RunnerDep, full: bool = False) -> HistoryOut:
        """Return the conversation of the current session, oldest message first.

        By default these are the messages the model is working with. `full=true` returns the whole conversation as it was
        written, with each compaction's summary (role `summary`) where it was made.
        """
        messages = await runner.client.session.history(full=full)
        return HistoryOut(messages=[message_out(message) for message in messages])

    @protected.get("/usage", response_model=UsageOut, tags=["usage"])
    async def usage_of_session(runner: RunnerDep) -> UsageOut:
        """Return what this session has spent, in this process and before it was resumed."""
        return usage_out(runner.client.usage)

    @protected.get("/usage/ledger", response_model=WorkspaceUsageOut, tags=["usage"])
    async def usage_ledger(runner: RunnerDep) -> WorkspaceUsageOut:
        """Return what the workspace's stored sessions have spent: by session, model and day.

        This is the ``/usage`` page's data, read back from the conversations, so it covers every session of the
        workspace and not only this one.
        """
        return ledger_out(await runner.usage_ledger())

    @protected.get("/sessions/current/stats", response_model=SessionStatsOut | None, tags=["sessions"])
    async def stats_of_session(runner: RunnerDep) -> SessionStatsOut | None:
        """Return the stored totals of the current session: entries, replies, tokens and the cached share."""
        found = await runner.session_stats(None)
        return stats_out(found[0]) if found else None

    @protected.get("/sessions/stats", response_model=SessionStatsListOut, tags=["sessions"])
    async def stats_of_sessions(
        runner: RunnerDep, ids: Annotated[str, Query(description="The session ids, comma separated")] = ""
    ) -> SessionStatsListOut:
        """Return the stored totals of named sessions, as the terminal's ``/resume`` panel lists its columns."""
        wanted = [part.strip() for part in ids.split(",") if part.strip()][:200]
        return SessionStatsListOut(stats=[stats_out(item) for item in await runner.session_stats(wanted)])

    @protected.get("/sessions/current/self-compaction", response_model=SelfCompactionOut, tags=["sessions"])
    async def self_compaction(runner: RunnerDep) -> SelfCompactionOut:
        """Whether the model may compact this session itself, and the session's own choice."""
        choice, effective = runner.self_compaction()
        return SelfCompactionOut(choice=choice, effective=effective)

    @protected.put("/sessions/current/self-compaction", response_model=SelfCompactionOut, tags=["sessions"])
    async def set_self_compaction(body: SelfCompactionUpdate, runner: RunnerDep) -> SelfCompactionOut:
        """Let the model compact this session itself (``true``), stop it (``false``), or follow the default (``null``)."""
        effective = await runner.use_self_compaction(body.choice)
        return SelfCompactionOut(choice=body.choice, effective=effective)

    @protected.post("/prompts", tags=["prompts"], responses={200: {"content": {"text/event-stream": {}}}})
    async def prompts(request: PromptRequest, runner: RunnerDep) -> StreamingResponse:
        """Run one prompt and stream it as server-sent events; see the guide for the frames.

        The stream ends with ``result`` when the model finished, ``error`` when the run failed, and ``cancelled`` when
        it was stopped; closing the connection stops the run. An approval or question the request defers arrives as a
        frame and is answered through ``/runs/approvals`` or ``/runs/questions``.
        """
        return stream_of(runner, request)

    @protected.post("/runs/resume", tags=["prompts"], responses={200: {"content": {"text/event-stream": {}}}})
    async def resume_run(request: ResumeRequest, runner: RunnerDep) -> StreamingResponse:
        """Continue the interrupted request where it stopped, streaming it like ``/prompts``.

        ``409 nothing_to_do`` (as an ``error`` frame) when there is nothing to pick up.
        """
        return stream_of(runner, request, resume=True)

    @protected.get("/runs/current", response_model=RunStateOut, tags=["prompts"])
    async def run_state(runner: RunnerDep) -> RunStateOut:
        """Say whether a run is going and what it waits on, so a reconnecting client can pick it up."""
        return RunStateOut(running=runner.busy, pending=runner.pending)

    @protected.get("/runs/resumable", response_model=ResumableOut, tags=["prompts"])
    async def resumable(runner: RunnerDep) -> ResumableOut:
        """Say where the conversation was interrupted, or that it was not."""
        info = await runner.resumable()
        if info is None:
            return ResumableOut(resumable=False)
        return ResumableOut(resumable=True, kind=info.kind, description=info.description)

    @protected.post("/runs/approvals", response_model=ResolvedOut, tags=["prompts"])
    async def answer_approval(body: ApprovalAnswer, runner: RunnerDep) -> ResolvedOut:
        """Approve or deny the shell command the run waits on."""
        resolved = await runner.resolve_approval(body.call_id, body.approve, body.remember)
        return ResolvedOut(resolved=resolved)

    @protected.post("/runs/questions", response_model=ResolvedOut, tags=["prompts"])
    async def answer_question(body: QuestionAnswer, runner: RunnerDep) -> ResolvedOut:
        """Answer the question the model asked, or decline it with ``null``."""
        return ResolvedOut(resolved=await runner.resolve_question(body.call_id, body.answer))

    @protected.post("/runs/steer", response_model=SteeredOut, tags=["prompts"])
    async def steer(body: SteerIn, runner: RunnerDep) -> SteeredOut:
        """Send a message into the run in progress; it drops what it was doing to take it into account."""
        return SteeredOut(steered=runner.steer(body.text))

    @protected.post("/runs/cancel", response_model=CancelledOut, tags=["prompts"])
    async def cancel_run(runner: RunnerDep) -> CancelledOut:
        """Stop the run in progress, if there is one; its stream ends with ``cancelled``."""
        return CancelledOut(cancelled=await runner.cancel())

    @protected.post("/sessions/current/ask", response_model=AnswerOut, tags=["sessions"])
    async def ask_side_question(body: SideQuestionRequest, runner: RunnerDep) -> AnswerOut:
        """Ask something answered from the conversation but kept out of it, as ``/btw`` does."""
        if runner.busy:
            raise SessionBusyError("A run is already in progress; ask again when it ends")
        return AnswerOut(answer=await runner.client.session.ask(body.question, timeout=body.timeout))

    @protected.post(
        "/sessions/current/ask/stream", tags=["sessions"], responses={200: {"content": {"text/event-stream": {}}}}
    )
    async def ask_side_question_stream(body: SideQuestionRequest, runner: RunnerDep) -> StreamingResponse:
        """Ask a side question and stream the answer as it is written, in the frames ``/prompts`` uses.

        The answer arrives as ``text_delta`` events and the stream ends with ``result``, ``error`` or ``cancelled``;
        ``/runs/cancel`` stops it. Like the plain endpoint, nothing of it joins the conversation.
        """
        if runner.busy:
            raise SessionBusyError("A run is already in progress; ask again when it ends")
        if not runner.ready:
            raise NoModelError("No model is configured; add one with POST /models")

        async def frames() -> AsyncIterator[bytes]:
            try:
                async for name, payload in runner.ask_stream(body.question, body.timeout):
                    yield sse_frame(name, payload)
            except Exception as error:  # noqa: BLE001 - the status line is gone; the failure goes down the stream
                _, code = failure_of(error)
                yield sse_frame("error", error_body(code, str(error)))

        return StreamingResponse(
            frames(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )

    @protected.post("/sessions/current/name", response_model=SessionOut, tags=["sessions"])
    async def name_session(runner: RunnerDep) -> SessionOut:
        """Ask the model for a name for this conversation, and give it one."""
        session = runner.client.session
        title = await session.name_it()
        return SessionOut(id=session.id, title=title, current=True)

    @protected.get("/sessions/current/export", tags=["sessions"], response_class=Response)
    async def export_session(runner: RunnerDep) -> Response:
        """Return the conversation as a standalone HTML page, to show or download."""
        session = runner.client.session
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as file:
            path = Path(file.name)
        try:
            await session.export(path)
            page = path.read_text(encoding="utf-8")
        finally:
            path.unlink(missing_ok=True)
        return Response(
            content=page,
            media_type="text/html; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="zettcode-{session.id[:8]}.html"'},
        )

    @protected.get("/plugins", response_model=PluginsOut, tags=["models"])
    async def plugins(runner: RunnerDep) -> PluginsOut:
        """List the plugins this server loaded, and the ones that could not load."""
        report = runner.client.plugins
        return PluginsOut(loaded=list(report.loaded), failures=list(report.failures))

    @protected.get("/mentions", response_model=MentionsOut, tags=["models"])
    async def mentions(
        runner: RunnerDep,
        query: Annotated[str, Query(description="What was typed after the @, without it")] = "",
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> MentionsOut:
        """List the files, skills and plugin resources an ``@`` in the prompt can reference."""
        return MentionsOut(mentions=[mention_out(item) for item in await runner.mentions(query, limit)])

    @protected.post("/doctor", response_model=DoctorOut, tags=["models"])
    async def doctor(runner: RunnerDep, body: DoctorRequest | None = None) -> DoctorOut:
        """Ask every configured model one short question and report which of them answer, as ``zettcode doctor``."""
        timeout = 30.0 if body is None else body.timeout
        return DoctorOut(checks=[check_out(item) for item in await runner.check_models(timeout)])

    app.include_router(protected)

    @app.exception_handler(StarletteHTTPException)
    async def http_failure(request: Request, error: StarletteHTTPException) -> JSONResponse:
        """Write an HTTP failure in the same shape as every other one."""
        code = "unauthorized" if error.status_code == 401 else "not_found" if error.status_code == 404 else "invalid"
        return JSONResponse(
            error_body(code, str(error.detail)), status_code=error.status_code, headers=dict(error.headers or {})
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_body(request: Request, error: RequestValidationError) -> JSONResponse:
        """Report a body the schema refused, with the field that was wrong."""
        problems = "; ".join(
            f"{'.'.join(str(part) for part in item['loc'][1:])}: {item['msg']}" for item in error.errors()
        )
        return JSONResponse(error_body("invalid", problems or "The request is not valid"), status_code=422)

    @app.middleware("http")
    async def failures(request: Request, call_next):
        """Turn an SDK failure into a status a client can branch on.

        A middleware rather than an exception handler for ``Exception``: Starlette's handler for it answers and then
        re-raises, which every in-process client (and the tests) sees instead of the response.
        """
        try:
            return await call_next(request)
        except Exception as error:  # noqa: BLE001 - this is the one place a failure becomes a response
            status, code = failure_of(error)
            return JSONResponse(error_body(code, str(error) or type(error).__name__), status_code=status)

    return app


__all__ = ["ApprovalPolicy", "ClientFactory", "create_app", "error_body", "failure_of", "result_payload", "sse_frame"]
