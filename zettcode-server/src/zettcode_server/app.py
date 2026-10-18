"""The FastAPI application: the endpoints, the error shapes, and the one run in progress.

Every endpoint is a thin move on the SDK. What this module owns is the contract: which status a failure becomes, what
a stream frame looks like, and that a second prompt while one runs is refused rather than queued.
"""

from __future__ import annotations

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

from . import __version__
from .runner import Request as RunRequest
from .runner import Runner, prepare, result_payload
from .schemas import (
    AnswerOut,
    ApprovalAnswer,
    ApprovalPolicy,
    CancelledOut,
    CompactionOut,
    ContextOut,
    CurrentSessionOut,
    ErrorOut,
    HealthOut,
    HistoryOut,
    ModelsOut,
    PluginsOut,
    PromptRequest,
    QuestionAnswer,
    RenameRequest,
    ResolvedOut,
    ResumableOut,
    ResumeRequest,
    RunStateOut,
    SessionCreate,
    SessionOut,
    SessionsOut,
    SettingsOut,
    SettingsUpdate,
    SideQuestionRequest,
    SteeredOut,
    SteerIn,
    UsageOut,
)
from .serialize import (
    compaction_out,
    context_out,
    current_session_out,
    message_out,
    model_out,
    session_out,
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
        """Say that the server is up, and which session and workspace it serves."""
        return HealthOut(
            version=__version__,
            workspace=str(settings.workspace),
            session=runner.client.session.id,
            busy=runner.busy,
        )

    @protected.get("/models", response_model=ModelsOut, tags=["models"])
    async def models(runner: RunnerDep) -> ModelsOut:
        """List the configured models and say which one the next prompt would use."""
        client = runner.client
        return ModelsOut(models=[model_out(model) for model in client.models], current=client.model.name)

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
        """Change the model, the reasoning effort or the permission level for the prompts that follow."""
        if update.model is None and update.effort is None and update.permission is None:
            raise ValueError("Name at least one of model, effort or permission")
        client = runner.client
        if update.model is not None:
            client.use_model(update.model)
        if update.effort is not None:
            client.use_effort(update.effort)
        if update.permission is not None:
            client.use_permission(update.permission)
        return await settings_out(runner)

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
    async def history_of_session(runner: RunnerDep) -> HistoryOut:
        """Return the stored conversation of the current session, oldest message first."""
        messages = await runner.client.session.history()
        return HistoryOut(messages=[message_out(message) for message in messages])

    @protected.get("/usage", response_model=UsageOut, tags=["usage"])
    async def usage_of_session(runner: RunnerDep) -> UsageOut:
        """Return what this session has spent, in this process and before it was resumed."""
        return usage_out(runner.client.usage)

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
