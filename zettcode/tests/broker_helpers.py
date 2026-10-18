"""Shared pieces for the broker tests: a peer that speaks the protocol by hand, and a broker to talk to."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import secrets
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from websockets.asyncio.client import connect

from zettcode.broker.client import BrokerClient, Incoming, Receipt, SessionInfo
from zettcode.broker.files import Note, remove_note, write_note
from zettcode.broker.protocol import MAX_BODY, PROTOCOL_VERSION
from zettcode.broker.server import Broker

TOKEN = "test-token"


async def eventually(check: Callable[[], Any], timeout: float = 2.0, *, interval: float = 0.01) -> Any:
    """Wait until ``check()`` is truthy and return it; fail with what it last said."""
    deadline = asyncio.get_running_loop().time() + timeout
    value = check()
    while not value:
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError(f"condition not met within {timeout}s (last value: {value!r})")
        await asyncio.sleep(interval)
        value = check()
    return value


def reason(line: dict[str, Any]) -> str | None:
    """Return the reason an answer's error carries, or ``None`` when it is not an error."""
    error = line.get("error")
    return error["reason"] if isinstance(error, dict) else None


class RawPeer:
    """One session connected to a broker, spoken by hand: every line it receives is kept, and nothing is answered for it.

    It is a real WebSocket for what a session hears and says, and a real HTTP client for sending. Deliveries are
    answered on demand with :meth:`accept` or :meth:`refuse`, so a test decides when, and whether, the recipient
    answers.
    """

    def __init__(self, websocket: Any, port: int, token: str) -> None:
        self.websocket = websocket
        self.port = port
        self.lines: list[dict[str, Any]] = []
        self.key = ""
        self.eof = asyncio.Event()
        self.close_code: int | None = None
        self._numbers = iter(range(1, 10**6))
        self._answered: set[Any] = set()
        self._http_token = token
        self._http: httpx.AsyncClient | None = None
        self._reading = asyncio.ensure_future(self._read())

    @classmethod
    async def connect(cls, port: int, *, hello: bool = True, token: str | None = TOKEN, path: str = "/inbox"):
        headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
        websocket = await connect(
            f"ws://127.0.0.1:{port}{path}", additional_headers=headers, proxy=None, compression=None, max_size=MAX_BODY
        )
        peer = cls(websocket, port, token or "")
        if hello:
            first = await eventually(lambda: next((x for x in peer.lines if x.get("op") == "hello"), None))
            peer.key = first["key"]
        return peer

    async def _read(self) -> None:
        try:
            async for raw in self.websocket:
                with contextlib.suppress(ValueError):
                    self.lines.append(json.loads(raw))
        except Exception:  # noqa: BLE001 - a closed connection ends the reading, however it closed
            pass
        finally:
            self.close_code = self.websocket.close_code
            self.eof.set()

    async def send(self, line: dict[str, Any]) -> None:
        await self.websocket.send(json.dumps(line))

    async def send_raw(self, data: str | bytes) -> None:
        await self.websocket.send(data)

    async def announce_frame(self, length: int) -> None:
        """Say that a text frame of ``length`` bytes is coming, and send none of it.

        Sending a body past the limit is a race of the test's own making: the server refuses on the header and
        hangs up while the body is still being written, the kernel answers the unread bytes with a reset, and
        the reset can overtake the close frame, so the sender sees a broken pipe instead of the 1009 it is
        checking for. The header alone is all the server needs to refuse, and leaves nothing unread behind.
        """
        masked = 0x80
        header = bytes([0x81, masked | 127]) + length.to_bytes(8, "big") + bytes(4)  # text, FIN, 8-byte length, mask
        self.websocket.transport.write(header)

    async def call(self, op: str, timeout: float = 3.0, **fields: Any) -> dict[str, Any]:
        """Say something over the WebSocket and return the ``done`` or ``refused`` that answers it."""
        number = next(self._numbers)
        await self.send({"op": op, "n": number, **fields})
        return await eventually(lambda: next((x for x in self.lines if x.get("n") == number), None), timeout)

    async def register(
        self, session_id: str, title: str = "", *, status: str = "idle", workspace: str = "/w", **more: Any
    ) -> dict[str, Any]:
        return await self.call(
            "session", session_id=session_id, title=title, workspace=workspace, status=status, **more
        )

    @property
    def http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                base_url=f"http://127.0.0.1:{self.port}",
                headers={"Authorization": f"Bearer {self._http_token}", "X-Session-Key": self.key},
                trust_env=False,
                timeout=15,
            )
        return self._http

    async def post(self, to: Any = None, text: Any = None, **more: Any) -> dict[str, Any]:
        """Send a message as this session, and return the broker's answer (an ``error`` when it was refused)."""
        body = {k: v for k, v in {"to": to, "text": text}.items() if v is not None} | more
        response = await self.http.post("/messages", json=body)
        answer = response.json()
        answer["status"] = response.status_code
        return answer

    def pushes(self, op: str = "roster") -> list[dict[str, Any]]:
        return [x for x in self.lines if x.get("op") == op]

    def rosters(self) -> list[list[dict[str, Any]]]:
        return [x["sessions"] for x in self.pushes("roster")]

    def listed(self) -> list[dict[str, Any]]:
        """The roster as of the last one pushed; empty until there is one."""
        rosters = self.rosters()
        return rosters[-1] if rosters else []

    def requests(self) -> list[dict[str, Any]]:
        return self.pushes("deliver")

    async def waiting(self) -> dict[str, Any]:
        """Wait for the next delivery nobody has answered, and return it."""
        return await eventually(lambda: next((r for r in self.requests() if r["id"] not in self._answered), None))

    async def accept(self, disposition: str = "started") -> dict[str, Any]:
        delivery = await self.waiting()
        self._answered.add(delivery["id"])
        await self.send({"op": "ack", "id": delivery["id"], "accepted": True, "reason": "", "disposition": disposition})
        return delivery

    async def refuse(self, why: str = "no") -> dict[str, Any]:
        delivery = await self.waiting()
        self._answered.add(delivery["id"])
        await self.send({"op": "ack", "id": delivery["id"], "accepted": False, "reason": why})
        return delivery

    async def ended(self, timeout: float = 2.0) -> bool:
        """Wait until the connection has closed."""
        try:
            await asyncio.wait_for(self.eof.wait(), timeout)
        except asyncio.TimeoutError:
            return False
        return True

    async def close(self) -> None:
        if self._http is not None:
            await self._http.aclose()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(self.websocket.close(), 1)
        self._reading.cancel()
        await asyncio.gather(self._reading, return_exceptions=True)


async def http(port: int, method: str, path: str, *, token: str | None = TOKEN, **options: Any) -> httpx.Response:
    """One HTTP request to a broker, with no environment proxy and the token unless told otherwise."""
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    headers.update(options.pop("headers", {}))
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", trust_env=False) as client:
        return await client.request(method, path, headers=headers, **options)


class Running:
    """A broker on a loopback port of its own, and the peers opened against it."""

    def __init__(self, broker: Broker) -> None:
        self.broker = broker
        self.peers: list[RawPeer] = []

    @property
    def port(self) -> int:
        return self.broker.port

    async def peer(self, session_id: str | None = None, title: str = "", **options: Any) -> RawPeer:
        peer = await RawPeer.connect(self.port, **options)
        self.peers.append(peer)
        if session_id is not None:
            answer = await peer.register(session_id, title)
            assert "error" not in answer, answer
        return peer

    async def aclose(self) -> None:
        for peer in self.peers:
            await peer.close()
        await self.broker.aclose()


async def started(**options: Any) -> Running:
    broker = Broker(TOKEN, **options)
    await broker.start()
    return Running(broker)


# -- the client side ---------------------------------------------------------------------------------------


class Host:
    """A broker run inside the test, announced in a directory the way a real one announces itself."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.broker: Broker | None = None
        self.token = ""

    async def start(self, **options: Any) -> Broker:
        self.token = secrets.token_urlsafe(12)
        options.setdefault("idle_exit", 60)
        self.broker = Broker(self.token, **options)
        port = await self.broker.start()
        write_note(self.directory, Note(pid=os.getpid(), port=port, token=self.token, version=PROTOCOL_VERSION))
        return self.broker

    async def stop(self) -> None:
        # What is being stopped is taken first: stopping takes a moment, a session that was told goodbye comes back
        # in that moment, and a test that restarts the host may have started a new one over this one by then.
        broker, token, self.broker = self.broker, self.token, None
        if broker is not None:
            await broker.aclose()
            remove_note(self.directory, token)


class Inbox:
    """What a session does with a message: remember it, and answer the way it was told to."""

    def __init__(self, receipt: Receipt | Callable[[Incoming], Receipt] | None = None) -> None:
        self.messages: list[Incoming] = []
        self.receipt = receipt if receipt is not None else Receipt(True, "", "started")

    def __call__(self, incoming: Incoming) -> Receipt:
        self.messages.append(incoming)
        return self.receipt(incoming) if callable(self.receipt) else self.receipt


class Spawns:
    """A stand-in for starting a broker: it records the attempt, and may bring one up."""

    def __init__(self, host: Host | None = None, *, fail: bool = False) -> None:
        self.calls: list[Path] = []
        self.host = host
        self.fail = fail

    def __call__(self, directory: Path) -> None:
        self.calls.append(directory)
        if self.fail:
            raise OSError("no such program")
        if self.host is not None:
            asyncio.ensure_future(self.host.start())


def client_for(directory: Path, **options: Any) -> BrokerClient:
    """A client with timings short enough for a test, and a spawner that starts nothing."""
    options.setdefault("spawner", Spawns())
    options.setdefault("backoff", (0.02, 0.05, 0.1))
    options.setdefault("connect_timeout", 0.5)
    options.setdefault("spawn_wait", 0.3)
    options.setdefault("reply_timeout", 3.0)
    return BrokerClient(directory=directory, **options)


def session(session_id: str, title: str = "", status: str = "idle") -> SessionInfo:
    return SessionInfo(session_id=session_id, title=title, workspace="/work", status=status)


HOLDER = """
import sys, time
from zettcode.filelock import SingletonLock
lock = SingletonLock(__import__("pathlib").Path(sys.argv[1]))
print("held" if lock.acquire() else "refused", flush=True)
time.sleep(120)
"""


def hold_lock(path: Path):
    """Start a process that holds the lock at ``path`` until it is killed: a broker that is alive, to the lock."""
    process = subprocess.Popen([sys.executable, "-c", HOLDER, str(path)], stdout=subprocess.PIPE, text=True)
    assert process.stdout is not None
    assert process.stdout.readline().strip() == "held"
    return process
