"""The broker as a server: a Starlette application (:mod:`.web`) over a :class:`~.hub.Hub`, served by uvicorn.

This is only the life of the server — bind a port, serve, say goodbye, and stop by itself some seconds after the last
session has left. What it serves is :mod:`.web`, what it decides is :mod:`.hub`, and the process around it (the lock,
the note, the signals) is :mod:`.runner`.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import socket
import time
from collections.abc import Callable

import uvicorn

from .hub import Hub
from .protocol import ACK_TIMEOUT, MAX_BODY, Limits
from .roster import Roster
from .store import Store
from .web import MAX_CONNECTIONS, Web

#: Seconds the broker waits with nobody connected before it exits.
IDLE_EXIT = 30.0


class _Uvicorn(uvicorn.Server):
    """uvicorn with its hands off the process: the runner owns the signals.

    By default it replaces the handlers for SIGINT and SIGTERM for as long as it serves, and sends the signal again
    once it has shut down, which would stop a broker that is in the middle of tidying up its files.
    """

    def install_signal_handlers(self) -> None:  # uvicorn before 0.29
        return None

    @contextlib.contextmanager
    def capture_signals(self):  # uvicorn from 0.29
        yield


class Broker:
    """The server. Start it, wait for it, close it.

    Args:
        token: What a request has to carry to be let in.
        host: The address to listen on. Never anything but loopback outside a test.
        port: The port; ``0`` lets the system pick one.
        idle_exit: Seconds with nobody connected before it stops.
        ack_timeout: Seconds to wait for a recipient to say it took a message.
        max_connections: Sessions at once; one more is turned away.
        ping_interval: Seconds between the WebSocket pings that find a session that has stopped answering; a session
            that does not answer one within ``ping_timeout`` is dropped.
        clock: Time source for the rate limit, injectable for tests.
        store: What the broker remembers across restarts (messages and groups); memory only when none is given.
    """

    def __init__(
        self,
        token: str,
        *,
        host: str = "127.0.0.1",
        port: int = 0,
        idle_exit: float = IDLE_EXIT,
        ack_timeout: float = ACK_TIMEOUT,
        max_connections: int = MAX_CONNECTIONS,
        ping_interval: float = 20.0,
        ping_timeout: float = 20.0,
        clock: Callable[[], float] = time.monotonic,
        store: Store | None = None,
    ) -> None:
        self.token = token
        self.host = host
        self.port = port
        self.idle_exit = idle_exit
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout
        self.hub = Hub(ack_timeout=ack_timeout, clock=clock, store=store)
        self.web = Web(
            self.hub, token, max_connections=max_connections, on_open=self._in_use, on_close=self._maybe_idle
        )
        self._uvicorn: _Uvicorn | None = None
        self._serving: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()
        self._idle: asyncio.TimerHandle | None = None

    @property
    def roster(self) -> Roster:
        """Who is registered."""
        return self.hub.roster

    @property
    def limits(self) -> Limits:
        """What the broker accepts."""
        return self.hub.limits

    @limits.setter
    def limits(self, limits: Limits) -> None:
        self.hub.limits = limits

    # -- the life of the server -------------------------------------------------------------------
    async def start(self) -> int:
        """Listen, and return the port. A port that cannot be had fails here, at once."""
        listener = self._bind()
        config = uvicorn.Config(
            self.web.app,
            log_config=None,
            log_level="warning",
            access_log=False,
            lifespan="off",
            ws_max_size=MAX_BODY,
            ws_ping_interval=self.ping_interval,
            ws_ping_timeout=self.ping_timeout,
            timeout_graceful_shutdown=2,
        )
        self._uvicorn = _Uvicorn(config)
        self._serving = asyncio.ensure_future(self._uvicorn.serve(sockets=[listener]))
        while not self._uvicorn.started:
            if self._serving.done():
                self._serving.result()
                raise OSError("the web server stopped while starting")
            await asyncio.sleep(0.005)
        self._maybe_idle()
        return self.port

    def _bind(self) -> socket.socket:
        """Bind the socket here rather than let uvicorn: the port is then known, and a bind that fails fails at once."""
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if os.name != "nt":  # on Windows the option would let a second broker share the port
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((self.host, self.port))
        except OSError:
            listener.close()
            raise
        self.port = listener.getsockname()[1]
        return listener

    def stop(self) -> None:
        """Ask the broker to end; :meth:`wait_closed` returns."""
        self._stopped.set()

    async def wait_closed(self) -> None:
        """Wait until the broker is idle or has been asked to stop."""
        await self._stopped.wait()

    async def aclose(self) -> None:
        """Say goodbye to every session and stop serving. Quick, and safe to call twice."""
        self.hub.closing = True
        self._stopped.set()
        self._in_use()
        serving, self._serving = self._serving, None
        if serving is not None and self._uvicorn is not None:
            self._uvicorn.should_exit = True  # it closes every WebSocket with 1012: "service restart"
            try:
                await asyncio.wait_for(asyncio.shield(serving), 5)
            except Exception:  # noqa: BLE001 - nothing here is worth failing an exit for
                serving.cancel()
                await asyncio.gather(serving, return_exceptions=True)

    # -- stopping when nobody needs it ------------------------------------------------------------
    def _in_use(self) -> None:
        """A session is here: the clock stops."""
        if self._idle is not None:
            self._idle.cancel()
            self._idle = None

    def _maybe_idle(self) -> None:
        """Nobody is here: the clock starts."""
        if not self.hub.sessions and not self.hub.closing:
            self._in_use()
            self._idle = asyncio.get_running_loop().call_later(self.idle_exit, self._expire)

    def _expire(self) -> None:
        self._idle = None
        if not self.hub.sessions:
            self.stop()


__all__ = ["IDLE_EXIT", "Broker"]
