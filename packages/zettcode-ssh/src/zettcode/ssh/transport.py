"""One bounded OpenSSH process per operation, with a fixed command and JSON on stdin."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shlex
import signal
from dataclasses import dataclass
from importlib.resources import files
from typing import Any

from zett_agent.messages import ImageBytesSource, ImageContent, TextContent

from zettcode.plugin_api import CHILD_STATE_ENV, PLUGIN_ARGS_ENV, subprocess_environment

from .remote import MAX_IMAGE, MAX_REQUEST, duration

MAX_RESPONSE = 6 * 1024 * 1024
#: How long the local side waits for an operation that is not a bash call. The worker's own alarm for those is
#: `remote.DEFAULT_ALARM` (125 s), and the margin over any deadline is what keeps the remote message the one seen.
OPERATION_TIMEOUT = 120.0
LOCAL_MARGIN = 15.0
HOST = re.compile(r"(?:[A-Za-z0-9_][A-Za-z0-9_.-]*@)?(?:[A-Za-z0-9_][A-Za-z0-9_.:-]*|\[[0-9a-fA-F:]+\])\Z")


@dataclass(frozen=True)
class Target:
    host: str
    path: str

    def __post_init__(self) -> None:
        if not isinstance(self.host, str) or not HOST.fullmatch(self.host) or len(self.host) > 255:
            raise ValueError("SSH host must be an OpenSSH alias or [user@]hostname, not options or a URL")
        if not isinstance(self.path, str) or not self.path.startswith("/") or any(ord(c) < 32 for c in self.path):
            raise ValueError("SSH workspace must be an absolute remote path without control characters")

    @classmethod
    def restore(cls, state: dict[str, Any]) -> Target:
        if not isinstance(state, dict) or set(state) != {"host", "path"}:
            raise ValueError("SSH child state must contain only host and path (no credentials)")
        return cls(state["host"], state["path"])

    def export(self) -> dict[str, Any]:
        return {"host": self.host, "path": self.path}


async def bounded(stream: asyncio.StreamReader, limit: int) -> bytes:
    chunks = bytearray()
    while True:
        part = await stream.read(min(8192, limit + 1 - len(chunks)))
        if not part:
            return bytes(chunks)
        chunks.extend(part)
        if len(chunks) > limit:
            raise ValueError("SSH response exceeds output limit")


async def cleanup(process: asyncio.subprocess.Process, tasks: list[asyncio.Task[Any]]) -> None:
    """Reap SSH without waiting on paused readers or pipes inherited by a descendant."""
    try:
        if process.returncode is None:
            if os.name == "posix":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except PermissionError:
                    # The group may have disappeared while SSH was exiting; do not hide its diagnostic.
                    process.kill()
            else:
                process.kill()
    except (ProcessLookupError, PermissionError):
        pass
    for task in tasks:
        if not task.done():
            task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    if process.stdin is not None:
        process.stdin.close()

    async def discard(stream: asyncio.StreamReader) -> None:
        while await stream.read(8192):
            pass

    # Cancelling the bounded readers leaves StreamReader buffers paused. Resume both while
    # waiting for the child: asyncio's process.wait() may otherwise never finish, even after kill.
    pending_tasks: list[asyncio.Task[Any]] = [asyncio.create_task(process.wait())]
    pending_tasks.extend(asyncio.create_task(discard(stream)) for stream in (process.stdout, process.stderr) if stream)
    _, pending = await asyncio.wait(pending_tasks, timeout=1)
    if pending:
        # StreamReader has no public close. A descendant outside SSH's process group can
        # retain its descriptors indefinitely; only this last-resort pipe close needs asyncio internals.
        transport = getattr(process, "_transport", None)
        for fd in (0, 1, 2):
            pipe = transport.get_pipe_transport(fd) if transport is not None else None
            if pipe is not None:
                pipe.close()
        await asyncio.wait(pending_tasks, timeout=1)
    for task in pending_tasks:
        if not task.done():
            task.cancel()
    await asyncio.gather(*pending_tasks, return_exceptions=True)


def decode_result(operation: str, result: Any) -> Any:
    if operation == "read" and isinstance(result, dict):
        data = base64.b64decode(result["image"], validate=True)
        if len(data) > MAX_IMAGE or result["media_type"] not in {"image/png", "image/jpeg", "image/gif", "image/webp"}:
            raise ValueError("Invalid remote image")
        return [
            TextContent(text=f"Remote image {result['name']}: {result['media_type']}, {len(data)} bytes"),
            ImageContent(source=ImageBytesSource(data=data, media_type=result["media_type"]), alt_text=result["name"]),
        ]
    if not isinstance(result, str):
        raise ValueError("Invalid SSH tool result")
    return result


async def diagnostic_stream(stream: asyncio.StreamReader, limit: int) -> bytes:
    """Retain a bounded diagnostic while continuously draining a long-lived channel."""
    result = bytearray()
    while True:
        chunk = await stream.read(8192)
        if not chunk:
            return bytes(result)
        result.extend(chunk[: max(0, limit - len(result))])


class Transport:
    def __init__(self, target: Target, *, persistent: bool = True) -> None:
        self.target = target
        self.persistent = persistent
        self._lock = asyncio.Lock()
        self._process: asyncio.subprocess.Process | None = None
        self._stderr: asyncio.Task[bytes] | None = None
        self._failure = ""
        self._closed = False
        self._sequence = 0

    @property
    def status(self) -> str:
        if self._failure:
            return "disconnected: " + self._failure
        if self._process is None:
            return "not connected"
        return "connected" if self._process.returncode is None else "disconnected"

    async def _start(self) -> asyncio.subprocess.Process:
        if self._closed:
            raise RuntimeError("SSH channel was closed by its owner; old targets cannot reconnect")
        if self._failure:
            # Only a new explicit tool request may reconnect. Never replay the interrupted request.
            self._failure = ""
        if self._process is not None:
            if self._process.returncode is not None:
                raise RuntimeError("SSH channel closed; the next request reconnects (this one was not retried)")
            return self._process
        payload = files("zettcode.ssh").joinpath("remote.py").read_text(encoding="utf-8")
        # Worker has no dependencies and never listens on TCP. Isolated Python excludes repository imports.
        command = "python3 -I -c " + shlex.quote(payload) + " --worker"
        environment = dict(subprocess_environment() or os.environ)
        environment.pop(CHILD_STATE_ENV, None)
        environment.pop(PLUGIN_ARGS_ENV, None)
        self._process = await asyncio.create_subprocess_exec(
            "ssh",
            "-T",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "ConnectTimeout=10",
            "-o",
            "ConnectionAttempts=1",
            "-o",
            "ServerAliveInterval=15",
            "-o",
            "ServerAliveCountMax=2",
            "--",
            self.target.host,
            command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=environment,
            start_new_session=os.name == "posix",
            limit=MAX_RESPONSE + 1,
        )
        assert self._process.stderr is not None
        self._stderr = asyncio.create_task(diagnostic_stream(self._process.stderr, 16 * 1024))
        return self._process

    async def aclose(self) -> None:
        self._closed = True
        # A request in flight holds the lock for its own deadline; shutting the channel down must not wait that long.
        try:
            await asyncio.wait_for(self._lock.acquire(), 5)
        except (asyncio.TimeoutError, TimeoutError):
            await self._close()
            return
        try:
            await self._close()
        finally:
            self._lock.release()

    async def _close(self) -> None:
        process, self._process = self._process, None
        tasks = [self._stderr] if self._stderr is not None else []
        self._stderr = None
        if process is not None:
            await cleanup(process, tasks)

    async def _exchange(self, operation: str, arguments: dict[str, Any]) -> Any:
        async with self._lock:
            self._sequence += 1
            request = json.dumps(
                {"id": self._sequence, "operation": operation, "workspace": self.target.path, "arguments": arguments},
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
            if len(request) > MAX_REQUEST:
                raise ValueError("SSH request exceeds 4 MiB")
            timeout = duration(arguments.get("timeout_seconds", 60)) if operation == "bash" else OPERATION_TIMEOUT
            try:
                process = await self._start()
                assert process.stdin is not None and process.stdout is not None

                async def exchange() -> bytes:
                    assert process.stdin is not None and process.stdout is not None
                    try:
                        process.stdin.write(request + b"\n")
                        await process.stdin.drain()
                    except (BrokenPipeError, ConnectionResetError):
                        pass  # Read stderr on EOF so authentication failures retain their diagnostic.
                    output = await process.stdout.readline()
                    if not output:
                        error = await self._stderr if self._stderr is not None else b""
                        raise RuntimeError("SSH channel closed: " + error.decode("utf-8", errors="replace"))
                    if len(output) > MAX_RESPONSE or not output.endswith(b"\n"):
                        raise ValueError("SSH response exceeds output limit or is not framed")
                    return output

                output = await asyncio.wait_for(exchange(), timeout + LOCAL_MARGIN)
                response = json.loads(output)
                if (
                    not isinstance(response, dict)
                    or response.get("id") != self._sequence
                    or type(response.get("ok")) is not bool
                ):
                    raise ValueError("Invalid SSH protocol response")
            except BaseException as error:
                self._failure = f"SSH request interrupted ({type(error).__name__}); remote outcome may be unknown"
                cleaning = asyncio.create_task(self._close())
                while not cleaning.done():
                    try:
                        await asyncio.shield(cleaning)
                    except asyncio.CancelledError:
                        continue
                cleaning.result()
                raise
            if not response["ok"]:
                raise RuntimeError(f"Remote operation failed: {response.get('error', 'unknown error')}")
            return decode_result(operation, response.get("result"))

    async def run(self, operation: str, arguments: dict[str, Any]) -> Any:
        if self.persistent:
            return await self._exchange(operation, arguments)
        return await self._run_once(operation, arguments)

    async def _run_once(self, operation: str, arguments: dict[str, Any]) -> Any:
        timeout = duration(arguments.get("timeout_seconds", 60)) if operation == "bash" else OPERATION_TIMEOUT
        request = json.dumps(
            {"operation": operation, "workspace": self.target.path, "arguments": arguments},
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        if len(request) > MAX_REQUEST:
            raise ValueError("SSH request exceeds 4 MiB")
        payload = files("zettcode.ssh").joinpath("remote.py").read_text(encoding="utf-8")
        # Neither the login directory, remote workspace nor PYTHONPATH may supply payload imports.
        remote_command = "python3 -I -c " + shlex.quote(payload)
        environment = dict(subprocess_environment() or os.environ)
        # These belong to a local interpreter. A reader's SendEnv must not carry an SDK handoff remotely.
        environment.pop(CHILD_STATE_ENV, None)
        environment.pop(PLUGIN_ARGS_ENV, None)
        process = await asyncio.create_subprocess_exec(
            "ssh",
            "-T",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "ConnectTimeout=10",
            "-o",
            "ConnectionAttempts=1",
            "--",
            self.target.host,
            remote_command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=environment,
            start_new_session=os.name == "posix",
        )
        assert process.stdin is not None and process.stdout is not None and process.stderr is not None
        tasks: list[asyncio.Task[Any]] = []

        async def send() -> None:
            assert process.stdin is not None
            try:
                process.stdin.write(request)
                await process.stdin.drain()
                process.stdin.close()
                await process.stdin.wait_closed()
            except (BrokenPipeError, ConnectionResetError):
                # Authentication/connection failures may close stdin before a large request is sent.
                # Let the exit-code/stderr path report the actual SSH diagnostic.
                process.stdin.close()

        try:
            tasks = [
                asyncio.create_task(send()),
                asyncio.create_task(bounded(process.stdout, MAX_RESPONSE)),
                asyncio.create_task(bounded(process.stderr, 16 * 1024)),
                asyncio.create_task(process.wait()),
            ]
            _, output, error, code = await asyncio.wait_for(asyncio.gather(*tasks), timeout=timeout + LOCAL_MARGIN)
            if code:
                raise RuntimeError(f"SSH failed (exit {code}): {error.decode('utf-8', errors='replace')}")
            try:
                response = json.loads(output)
            except (ValueError, UnicodeDecodeError) as failure:
                raise ValueError("Invalid SSH protocol response (remote python3 is required)") from failure
            if not isinstance(response, dict) or type(response.get("ok")) is not bool:
                raise ValueError("Invalid SSH protocol response")
            if not response["ok"]:
                raise RuntimeError(f"Remote operation failed: {response.get('error', 'unknown error')}")
            if "result" not in response:
                raise ValueError("Missing SSH protocol result")
            return decode_result(operation, response["result"])
        finally:
            # Shield cleanup from a second cancellation without suppressing the original failure.
            cleaning = asyncio.create_task(cleanup(process, tasks))
            cancelled = False
            while not cleaning.done():
                try:
                    await asyncio.shield(cleaning)
                except asyncio.CancelledError:
                    cancelled = True
            cleaning.result()
            if cancelled:
                raise asyncio.CancelledError
