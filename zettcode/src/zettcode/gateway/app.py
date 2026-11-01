"""The gateway as a web application: sign-in, the JSON endpoints, the event socket, and the page itself.

Nothing here decides anything about sessions (that is :mod:`.service`); this is what any web service has: who is let
in, how a body is read, how a refusal is answered, how a WebSocket is read and written. Every route but the page, its
files and the sign-in asks for a signed-in browser (a cookie) or the token as a bearer.

The gateway can start agents that run commands, so a browser is trusted only after it has shown the token, the cookie
is not readable by the page's scripts and is not sent across sites, and a request that carries an ``Origin`` has to
carry the gateway's own.
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import logging
import os
import secrets
import sys
import time
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import HTTPConnection, Request
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.websockets import WebSocket, WebSocketDisconnect

from .backend import Backend, GatewayStartError, SdkBackend
from .runfile import clear as clear_runfile
from .runfile import write as write_runfile
from .service import Gateway, GatewayError
from .settings import Settings

logger = logging.getLogger("zettcode.gateway")

#: The folder that holds the page, its script and its style.
STATIC = Path(__file__).parent / "static"

#: What a checkout that has not built the page says instead of it.
NOT_BUILT = (
    "The gateway's page has not been built in this checkout. Run `make gateway-ui` (needs Node 20+), or install the "
    "published package, which carries it. The API is up."
)

#: The cookie a signed-in browser carries, and how long it stays good.
COOKIE = "zg_session"
COOKIE_SECONDS = 30 * 24 * 3600

#: The most a request body may be, in bytes. A message is at most 32,000 characters.
MAX_BODY = 256 * 1024

#: Wrong tokens tolerated in a window before sign-in is refused for a while.
LOGIN_FAILURES = 8
LOGIN_WINDOW = 600.0

#: What a WebSocket is closed with when it is not signed in.
UNAUTHORIZED = 4401

#: The names a browser on this machine reaches it by.
LOOPBACK_NAMES = frozenset({"127.0.0.1", "::1", "localhost"})

#: What the page may load: its own files, and inline styles (the math typesetter writes them) but never inline script, so a message with
#: markup in it has nowhere to run. Images from other sites are not loaded: a message cannot make the page call out.
POLICY = (
    "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; "
    "object-src 'none'; base-uri 'none'; "
    "form-action 'self'; frame-ancestors 'none'"
)


class Auth:
    """Who is signed in: the token, the cookies issued for it, and how many wrong tokens have been tried."""

    def __init__(self, token: str, clock: Callable[[], float] = time.monotonic) -> None:
        self.token = token
        self.clock = clock
        self._sessions: dict[str, float] = {}
        self._failures: deque[float] = deque()

    def token_ok(self, given: str) -> bool:
        """Return whether ``given`` is the token, compared in constant time."""
        return bool(self.token) and hmac.compare_digest(given.encode(), self.token.encode())

    def locked_out(self) -> bool:
        """Return whether too many wrong tokens were tried lately."""
        now = self.clock()
        while self._failures and now - self._failures[0] > LOGIN_WINDOW:
            self._failures.popleft()
        return len(self._failures) >= LOGIN_FAILURES

    def failed(self) -> None:
        """Count a wrong token."""
        self._failures.append(self.clock())

    def issue(self) -> str:
        """Return a new cookie value for a browser that showed the token."""
        value = secrets.token_urlsafe(32)
        self._sessions[value] = self.clock() + COOKIE_SECONDS
        return value

    def revoke(self, value: str | None) -> None:
        """Forget a cookie, so it no longer signs anybody in."""
        if value:
            self._sessions.pop(value, None)

    def cookie_ok(self, value: str | None) -> bool:
        """Return whether a cookie was issued and has not run out."""
        if not value:
            return False
        expires = self._sessions.get(value)
        if expires is None:
            return False
        if expires < self.clock():
            self._sessions.pop(value, None)
            return False
        return True

    @property
    def open(self) -> bool:
        """Return whether there is no token, so nothing is asked of a browser but that it is on this machine."""
        return not self.token

    def allowed(self, connection: HTTPConnection) -> bool:
        """Return whether a request or socket is signed in, by cookie or by bearer token.

        With no token every request is let in, but only one addressed to this machine by name: a page on another site
        can make a browser send requests to a local port, and a name that resolves to it (DNS rebinding) would
        otherwise be trusted as the page itself.
        """
        if self.open:
            return urlsplit("//" + connection.headers.get("host", "")).hostname in LOOPBACK_NAMES
        if self.cookie_ok(connection.cookies.get(COOKIE)):
            return True
        scheme, _, given = connection.headers.get("authorization", "").partition(" ")
        return scheme.lower() == "bearer" and self.token_ok(given.strip())


def same_origin(connection: HTTPConnection, *, required: bool = False) -> bool:
    """Return whether a request did not come from another site: it names this host in ``Origin``.

    A request with no ``Origin`` is let through unless ``required``: a browser sends one on every write and every socket,
    and with no token (nothing but this check stands between a page on another site and a gateway that runs commands) a
    program that writes to the gateway says where it is from too.
    """
    origin = connection.headers.get("origin")
    if not origin:
        return not required
    return urlsplit(origin).netloc == connection.headers.get("host", "")


class Headers:
    """ASGI middleware that puts the response headers every answer of the gateway carries on it."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def wrapped(message: Any) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                headers.extend(
                    (name.encode(), value.encode())
                    for name, value in (
                        ("content-security-policy", POLICY),
                        ("x-content-type-options", "nosniff"),
                        ("referrer-policy", "no-referrer"),
                        ("x-frame-options", "DENY"),
                    )
                )
            await send(message)

        await self.app(scope, receive, wrapped)


class Files(StaticFiles):
    """The page's files, always revalidated: the page and its script change together and must not be mixed."""

    def file_response(self, *args: Any, **kwargs: Any) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers["cache-control"] = "no-cache"
        return response


Handler = Callable[[Request], Awaitable[Any]]


def create_app(settings: Settings, backend: Backend | None = None, *, static: Path = STATIC) -> Starlette:
    """Return the application for these settings; a test gives a backend of its own, and the folder the page is in."""
    auth = Auth(settings.token)
    gateway = Gateway(backend if backend is not None else SdkBackend(settings.workspace, settings.directory), settings)

    @asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncIterator[None]:
        try:
            await gateway.start()
        except Exception as error:
            logger.exception("start.failed", extra={"host": settings.host, "port": settings.port})
            if isinstance(error, GatewayStartError):
                sys.stderr.write(f"zettcode gateway: {error}\n")
            raise
        # Written only once the gateway is a session: a second one that lost the session would otherwise replace
        # the record of the one that kept it. The record is what `zettcode gateway stop|restart` finds.
        write_runfile(settings)
        logger.info("start", extra={"host": settings.host, "port": settings.port})
        try:
            yield
        finally:
            clear_runfile(settings.directory, pid=os.getpid())
            await gateway.close()
            logger.info("stop", extra={"host": settings.host, "port": settings.port})

    # -- plumbing ---------------------------------------------------------------------------------
    def api(handler: Handler, *, public: bool = False) -> Callable[[Request], Awaitable[Response]]:
        """Wrap an endpoint: check who is asking, run it, and answer a refusal or a fault in the one shape."""

        async def route(request: Request) -> Response:
            try:
                if not public and not auth.allowed(request):
                    raise GatewayError(401, "unauthorized", "Sign in first")
                if request.method not in ("GET", "HEAD") and not same_origin(request, required=auth.open):
                    raise GatewayError(403, "forbidden", "This request came from another site")
                result = await handler(request)
                return result if isinstance(result, Response) else JSONResponse(result)
            except GatewayError as error:
                headers = {"retry-after": str(error.extra["retry_after"])} if "retry_after" in error.extra else None
                return JSONResponse(error.to_dict(), error.status, headers=headers)
            except Exception as error:  # noqa: BLE001 - one request failing must not end the server
                logger.exception("request.failed", extra={"method": request.method, "route": request.url.path})
                return JSONResponse(
                    {"error": {"code": "internal", "message": f"The request failed ({type(error).__name__})"}}, 500
                )

        return route

    async def body(request: Request) -> dict[str, Any]:
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > MAX_BODY:
            raise GatewayError(413, "too_long", "The request is too large")
        data = b""
        async for chunk in request.stream():
            data += chunk
            if len(data) > MAX_BODY:
                raise GatewayError(413, "too_long", "The request is too large")
        try:
            parsed = json.loads(data or b"{}")
        except ValueError:
            raise GatewayError(400, "invalid", "The body is not JSON") from None
        if not isinstance(parsed, dict):
            raise GatewayError(400, "invalid", "The body is a JSON object")
        return parsed

    # -- sign-in ----------------------------------------------------------------------------------
    async def session(request: Request) -> Any:
        return {"authenticated": auth.allowed(request), "open": auth.open}

    async def login(request: Request) -> Any:
        if auth.locked_out():
            raise GatewayError(429, "rate", "Too many wrong tokens; wait a few minutes", retry_after=60)
        given = (await body(request)).get("token")
        if not isinstance(given, str) or not auth.token_ok(given.strip()):
            auth.failed()
            await asyncio.sleep(0.4)
            raise GatewayError(401, "unauthorized", "That is not the token")
        response = JSONResponse({"authenticated": True})
        response.set_cookie(
            COOKIE,
            auth.issue(),
            max_age=COOKIE_SECONDS,
            httponly=True,
            samesite="strict",
            secure=request.url.scheme == "https",
            path="/",
        )
        return response

    async def logout(request: Request) -> Any:
        auth.revoke(request.cookies.get(COOKIE))
        response = JSONResponse({"authenticated": False})
        response.delete_cookie(COOKIE, path="/")
        return response

    # -- the endpoints ----------------------------------------------------------------------------
    async def status(_: Request) -> Any:
        return gateway.status()

    async def config(_: Request) -> Any:
        return gateway.config()

    async def dirs(request: Request) -> Any:
        return gateway.browse(request.query_params.get("path", ""))

    async def threads(_: Request) -> Any:
        return {"threads": gateway.threads(), "status": gateway.status()}

    async def graph(_: Request) -> Any:
        return await gateway.graph()

    async def older(request: Request) -> Any:
        return await gateway.older(request.query_params.get("before"), request.query_params.get("limit"))

    async def timeline(request: Request) -> Any:
        query = request.query_params
        return await gateway.timeline(query.get("since"), query.get("until"), query.get("limit"))

    async def thread(request: Request) -> Any:
        everything = request.query_params.get("all") in ("1", "true")
        return await gateway.thread(request.path_params["id"], everything=everything)

    async def read(request: Request) -> Any:
        await gateway.read(request.path_params["id"])
        return {"ok": True}

    async def recheck(request: Request) -> Any:
        return {"thread": await gateway.recheck(request.path_params["id"])}

    async def send(request: Request) -> Any:
        data = await body(request)
        text = data.get("text")
        reply = data.get("reply")
        if not isinstance(text, str) or (reply is not None and not isinstance(reply, bool)):
            raise GatewayError(400, "invalid", "text is a string and reply a boolean")
        return await gateway.send(request.path_params["id"], text, reply=reply) | {"status": gateway.status()}

    async def spawn(request: Request) -> Any:
        return await gateway.spawn(await body(request))

    async def stop(request: Request) -> Any:
        return await gateway.stop(request.path_params["id"])

    async def log(request: Request) -> Any:
        return await gateway.log(request.path_params["id"])

    async def index(_: Request) -> Response:
        page = static / "index.html"
        if not page.is_file():
            # The page is built from clients/gateway when a distribution is made and is not kept in the repository, so a
            # checkout that has not built it has an API and no page: say so, rather than answer 404 to the first request.
            return PlainTextResponse(NOT_BUILT, status_code=503)
        return FileResponse(page, headers={"cache-control": "no-store"})

    async def manifest(_: Request) -> Response:
        return FileResponse(
            static / "manifest.webmanifest",
            media_type="application/manifest+json",
            headers={"cache-control": "no-cache"},
        )

    # -- the event socket -------------------------------------------------------------------------
    async def events(websocket: WebSocket) -> None:
        if not auth.allowed(websocket) or not same_origin(websocket, required=auth.open):
            await websocket.close(UNAUTHORIZED)
            return
        await websocket.accept()
        queue = gateway.subscribe()

        async def pump() -> None:
            with contextlib.suppress(Exception):
                while True:
                    event = await queue.get()
                    if event.get("type") == "close":
                        await websocket.close(1013)  # "try again later": the page reconnects and reads everything again
                        return
                    await websocket.send_text(json.dumps(event, separators=(",", ":")))

        writer = asyncio.ensure_future(pump())
        try:
            while True:
                await websocket.receive_text()
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            writer.cancel()
            await asyncio.gather(writer, return_exceptions=True)
            gateway.unsubscribe(queue)

    routes = [
        Route("/", index),
        Route("/manifest.webmanifest", manifest),
        Route("/api/session", api(session, public=True)),
        Route("/api/login", api(login, public=True), methods=["POST"]),
        Route("/api/logout", api(logout, public=True), methods=["POST"]),
        Route("/api/status", api(status)),
        Route("/api/config", api(config)),
        Route("/api/dirs", api(dirs)),
        Route("/api/graph", api(graph)),
        Route("/api/graph/timeline", api(timeline)),
        Route("/api/graph/older", api(older)),
        Route("/api/threads", api(threads)),
        Route("/api/threads/{id}", api(thread)),
        Route("/api/threads/{id}/read", api(read), methods=["POST"]),
        Route("/api/threads/{id}/recheck", api(recheck), methods=["POST"]),
        Route("/api/threads/{id}/send", api(send), methods=["POST"]),
        Route("/api/daemons", api(spawn), methods=["POST"]),
        Route("/api/daemons/{id}", api(stop), methods=["DELETE"]),
        Route("/api/daemons/{id}/log", api(log)),
        WebSocketRoute("/api/events", events),
        Mount("/static", Files(directory=static, check_dir=False), name="static"),
    ]
    app = Starlette(routes=routes, lifespan=lifespan, middleware=[Middleware(Headers)])
    app.state.gateway = gateway
    app.state.auth = auth
    return app
