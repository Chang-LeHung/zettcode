"""The broker's face: a Starlette application. It turns HTTP and WebSocket traffic into calls on the :class:`~.hub.Hub`.

Nothing here decides anything about sessions or messages (that is the hub); this is the plumbing that is the same for
any web service: who is let in, how a body is read, how a refusal is answered, and how a WebSocket is read and
written. The routes are listed at the top of :mod:`.protocol`.
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import logging
import math
import time
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from .hub import Hub, Session
from .log import log
from .protocol import MAX_BODY, MAX_MESSAGE_BODY, Refused

logger = logging.getLogger("zettcode.broker")

#: Sessions at once. A person has a handful; this only has to stop a runaway.
MAX_CONNECTIONS = 512

#: What a WebSocket is closed with when it has no token (a code of our own, in the range for applications).
UNAUTHORIZED = 4401

#: What a WebSocket is closed with when there is no room, or the broker is going away ("try again later").
TRY_LATER = 1013

#: The HTTP status a refusal is answered with; what a program reads is the reason in the body.
STATUS = {
    "invalid": 400,
    "empty": 400,
    "self": 400,
    "auth": 401,
    "not_registered": 403,
    "denied": 403,
    "unknown": 404,
    "gone": 410,
    "ambiguous": 409,
    "duplicate": 409,
    "rejected": 409,
    "too_long": 413,
    "loop": 422,
    "rate": 429,
    "internal": 500,
    "busy": 503,
    "timeout": 504,
}


class Web:
    """The application: ``Web(...).app`` is what uvicorn serves.

    Args:
        hub: What every request is passed to.
        token: What a request has to carry to be let in.
        max_connections: Sessions at once; one more is turned away.
        on_open: Called when a session's WebSocket has been accepted.
        on_close: Called when it has ended.
    """

    def __init__(
        self,
        hub: Hub,
        token: str,
        *,
        max_connections: int = MAX_CONNECTIONS,
        on_open: Callable[[], None] = lambda: None,
        on_close: Callable[[], None] = lambda: None,
    ) -> None:
        self.hub = hub
        self.token = token
        self.max_connections = max_connections
        self.on_open = on_open
        self.on_close = on_close
        self.app = Starlette(
            routes=[
                Route("/health", self._health),
                Route("/sessions", self._sessions),
                Route("/messages", self._messages, methods=["POST"]),
                Route("/groups", self._groups, methods=["GET", "POST"]),
                Route("/history", self._history),
                Route("/graph", self._graph),
                Route("/timeline", self._timeline),
                Route("/older", self._older),
                WebSocketRoute("/inbox", self._inbox),
            ]
        )

    # -- who is let in ----------------------------------------------------------------------------
    def _allowed(self, headers: Any) -> bool:
        scheme, _, given = headers.get("authorization", "").partition(" ")
        return scheme.lower() == "bearer" and hmac.compare_digest(given.strip().encode(), self.token.encode())

    async def _guarded(self, request: Request, work: Callable[[Request], Awaitable[dict[str, Any]]]) -> JSONResponse:
        """Run a route that needs the token, and answer a refusal, or a fault, as the protocol says."""
        try:
            if not self._allowed(request.headers):
                raise Refused("auth", "this broker wants its token: Authorization: Bearer <token>")
            return JSONResponse(await work(request))
        except Refused as refused:
            return self._refusal(refused)
        except Exception as error:  # noqa: BLE001 - one request failing must not end the server
            logger.exception("request.failed", extra={"method": request.method, "route": request.url.path})
            log(f"a request failed: {error!r}")
            return self._refusal(Refused("internal", f"the request failed ({type(error).__name__})"))

    @staticmethod
    def _refusal(refused: Refused) -> JSONResponse:
        return JSONResponse({"error": refused.to_wire()}, STATUS.get(refused.reason, 400))

    # -- plain HTTP -------------------------------------------------------------------------------
    async def _health(self, request: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    async def _sessions(self, request: Request) -> JSONResponse:
        async def work(_: Request) -> dict[str, Any]:
            return self.hub.listing()

        return await self._guarded(request, work)

    async def _messages(self, request: Request) -> JSONResponse:
        async def work(asked: Request) -> dict[str, Any]:
            return await self.hub.send(
                asked.headers.get("x-session-key"), await self._json_object(asked, MAX_MESSAGE_BODY)
            )

        return await self._guarded(request, work)

    async def _groups(self, request: Request) -> JSONResponse:
        async def work(asked: Request) -> dict[str, Any]:
            key = asked.headers.get("x-session-key")
            if asked.method == "POST":
                return self.hub.manage_group(key, await self._json_object(asked))
            return self.hub.listing_groups(key)

        return await self._guarded(request, work)

    async def _history(self, request: Request) -> JSONResponse:
        async def work(asked: Request) -> dict[str, Any]:
            return self.hub.history(asked.headers.get("x-session-key"), dict(asked.query_params))

        return await self._guarded(request, work)

    async def _graph(self, request: Request) -> JSONResponse:
        async def work(_: Request) -> dict[str, Any]:
            return self.hub.graph()

        return await self._guarded(request, work)

    async def _older(self, request: Request) -> JSONResponse:
        async def work(asked: Request) -> dict[str, Any]:
            try:
                before = int(asked.query_params.get("before") or 0)
                limit = int(asked.query_params.get("limit") or 50)
            except ValueError:
                raise Refused("invalid", "before is a message id, limit a count") from None
            if before < 1:
                raise Refused("invalid", "before is a message id")
            return self.hub.older(before, limit)

        return await self._guarded(request, work)

    async def _timeline(self, request: Request) -> JSONResponse:
        async def work(asked: Request) -> dict[str, Any]:
            params = asked.query_params
            try:
                until = float(params.get("until") or time.time())
                since = float(params.get("since") or until - 3600)
                limit = int(params.get("limit") or 500)
            except ValueError:
                raise Refused("invalid", "since and until are epoch seconds, limit a count") from None
            if not (math.isfinite(since) and math.isfinite(until)) or since > until:
                raise Refused("invalid", "since must not be after until")
            return self.hub.timeline(since, until, limit)

        return await self._guarded(request, work)

    @staticmethod
    async def _json_object(request: Request, limit: int = MAX_BODY) -> dict[str, Any]:
        """Read the JSON object a request carries, refusing one past the limit before it is all in memory."""
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > limit:
            raise Refused("too_long", "the request is too large")
        data = b""
        async for chunk in request.stream():
            data += chunk
            if len(data) > limit:
                raise Refused("too_long", "the request is too large")
        try:
            body = json.loads(data)
        except ValueError:
            raise Refused("invalid", "the body is not JSON") from None
        if not isinstance(body, dict):
            raise Refused("invalid", "the body is a JSON object")
        return body

    # -- the WebSocket of a session ---------------------------------------------------------------
    async def _inbox(self, websocket: WebSocket) -> None:
        if not self._allowed(websocket.headers):
            await websocket.close(UNAUTHORIZED)
            return
        if self.hub.closing or len(self.hub.sessions) >= self.max_connections:
            await websocket.close(TRY_LATER)
            return
        await websocket.accept()
        session = self.hub.admit(lambda code: self._close_soon(websocket, code))
        logger.debug("session.open", extra={"connection": session.number})
        self.on_open()
        writer = asyncio.ensure_future(self._write(websocket, session))
        try:
            await self._read(websocket, session)
        finally:
            writer.cancel()
            await asyncio.gather(writer, return_exceptions=True)
            self.hub.release(session)
            logger.debug("session.close", extra={"connection": session.number})
            self.on_close()

    async def _read(self, websocket: WebSocket, session: Session) -> None:
        """Hand the hub each line the session sends, until it goes or says something that is not a JSON object."""
        try:
            while isinstance(line := json.loads(await websocket.receive_text()), dict):
                self.hub.hear(session, line)
        except (WebSocketDisconnect, ValueError, KeyError, RuntimeError):
            pass  # gone, or not JSON: either way it is over

    @staticmethod
    async def _write(websocket: WebSocket, session: Session) -> None:
        """Send what is queued for a session, one line at a time, in order."""
        try:
            while True:
                await websocket.send_text(json.dumps(await session.next_line(), separators=(",", ":")))
        except (WebSocketDisconnect, RuntimeError, OSError):
            return  # the reader is gone; that is how a session ends, not a fault to report
        except Exception:  # noqa: BLE001 - anything else is worth a trace in the log
            logger.exception("session.write_failed", extra={"connection": session.number})
            return

    @staticmethod
    def _close_soon(websocket: WebSocket, code: int) -> None:
        """Close a WebSocket from code that cannot wait for it (the hub's, when a session has stopped reading)."""

        async def close() -> None:
            with contextlib.suppress(Exception):
                await websocket.close(code)

        asyncio.ensure_future(close())
