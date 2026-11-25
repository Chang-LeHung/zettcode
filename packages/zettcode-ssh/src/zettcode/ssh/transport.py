"""One bounded OpenSSH process per operation, with a fixed command and JSON on stdin."""

from __future__ import annotations

import asyncio
import atexit
import base64
import json
import os
import re
import shlex
import shutil
import signal
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

from zett_agent.messages import ImageBytesSource, ImageContent, TextContent

from zettcode.plugin_api import CHILD_STATE_ENV, PLUGIN_ARGS_ENV, subprocess_environment

from .remote import MAX_IMAGE, MAX_REQUEST, duration

MAX_RESPONSE = 6 * 1024 * 1024
HOST = re.compile(r"(?:[A-Za-z0-9_][A-Za-z0-9_.-]*@)?(?:[A-Za-z0-9_][A-Za-z0-9_.:-]*|\[[0-9a-fA-F:]+\])\Z")
USER = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}\Z")
AUTHS = ("key", "password")


@dataclass(frozen=True)
class Target:
    """Where remote tools run and how OpenSSH signs in; never a secret."""

    host: str
    path: str
    user: str | None = None
    auth: str = "key"

    def __post_init__(self) -> None:
        if not isinstance(self.host, str) or not HOST.fullmatch(self.host) or len(self.host) > 255:
            raise ValueError("SSH host must be an OpenSSH alias or [user@]hostname, not options or a URL")
        if not isinstance(self.path, str) or not self.path.startswith("/") or any(ord(c) < 32 for c in self.path):
            raise ValueError("SSH workspace must be an absolute remote path without control characters")
        if self.user is not None and (not isinstance(self.user, str) or not USER.fullmatch(self.user)):
            raise ValueError("SSH user must be a plain account name, not options")
        if self.auth not in AUTHS:
            raise ValueError("SSH sign-in is 'key' or 'password'")

    @classmethod
    def restore(cls, state: dict[str, Any]) -> Target:
        """Restore a descriptor without ever accepting a credential.

        Older descriptors carried only ``host`` and ``path``; the user and sign-in method are optional additions.
        """
        if not isinstance(state, dict) or not {"host", "path"} <= set(state) <= {"host", "path", "user", "auth"}:
            raise ValueError("SSH child state may contain only host, path, user and auth (no credentials)")
        return cls(state["host"], state["path"], state.get("user"), state.get("auth", "key"))

    def export(self) -> dict[str, Any]:
        return {"host": self.host, "path": self.path, "user": self.user, "auth": self.auth}


class Askpass:
    """Hand a password to OpenSSH beside argv, not in it, and never in durable state.

    OpenSSH reads a password from the terminal, which a tool has none of. With ``SSH_ASKPASS_REQUIRE=force`` it
    runs a helper instead, so the password reaches it through a private file (directory 0700, file 0600) whose path
    is in the helper. The environment and argv of the ssh process carry only that path.
    """

    def __init__(self) -> None:
        self.directory: Path | None = None
        self._atexit: Callable[[], None] | None = None

    def environment(self, password: str) -> dict[str, str]:
        """Return the environment additions, writing the helper on first use and reusing it after a reconnect."""
        if self.directory is None:
            self.prepare(password)
        else:
            try:
                saved = (self.directory / "secret").read_text(encoding="utf-8")
                (self.directory / "askpass").read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                self.close()
                return self.prepare(password)
            if saved != password + "\n":
                raise ValueError("An SSH askpass helper cannot change password; close it before preparing another")
        assert self.directory is not None
        return {
            "SSH_ASKPASS": str(self.directory / "askpass"),
            "SSH_ASKPASS_REQUIRE": "force",
            "DISPLAY": os.environ.get("DISPLAY", ":0"),
        }

    @property
    def ready(self) -> bool:
        return self.directory is not None

    def prepare(self, password: str) -> dict[str, str]:
        """Write the helper and return the environment additions OpenSSH needs."""
        if not password or any(char in password for char in "\r\n\0"):
            raise ValueError("An SSH password must be non-empty single-line text")
        directory = Path(tempfile.mkdtemp(prefix="zettcode-ssh-askpass-"))
        self.directory = directory
        try:
            os.chmod(directory, 0o700)
            secret = directory / "secret"
            descriptor = os.open(secret, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
                handle.write(password + "\n")
            script = directory / "askpass"
            script.write_text(f"#!/bin/sh\nexec /bin/cat {shlex.quote(str(secret))}\n", encoding="utf-8")
            os.chmod(script, 0o700)
            # A process that exits without closing the channel still takes the password with it.
            directory_path = directory

            def remove() -> None:
                shutil.rmtree(directory_path, ignore_errors=True)

            atexit.register(remove)
            self._atexit = remove
        except OSError:
            self.close()
            raise
        return self.environment(password)

    def close(self) -> None:
        """Remove the helper and the password with it."""
        if self._atexit is not None:
            atexit.unregister(self._atexit)
            self._atexit = None
        if self.directory is not None:
            shutil.rmtree(self.directory, ignore_errors=True)
            self.directory = None


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
        transport = process._transport  # type: ignore[attr-defined]
        for fd in (0, 1, 2):
            pipe = transport.get_pipe_transport(fd)
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
    def __init__(self, target: Target, *, password: str | None = None, persistent: bool = True) -> None:
        self.target = target
        self.password = password
        self.persistent = persistent
        self._lock = asyncio.Lock()
        self._process: asyncio.subprocess.Process | None = None
        self._stderr: asyncio.Task[bytes] | None = None
        self._failure = ""
        self._closed = False
        self._sequence = 0
        self._askpass = Askpass() if target.auth == "password" else None

    def _ssh_arguments(self) -> list[str]:
        """Return the OpenSSH options for this target's sign-in method and account."""
        arguments = [
            "-T",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "ConnectTimeout=10",
            "-o",
            "ConnectionAttempts=1",
        ]
        if self.target.auth == "password":
            arguments += [
                "-o",
                "BatchMode=no",
                "-o",
                "NumberOfPasswordPrompts=1",
                "-o",
                "PreferredAuthentications=password,keyboard-interactive",
                "-o",
                "PubkeyAuthentication=no",
            ]
        else:
            arguments += ["-o", "BatchMode=yes"]
        arguments += ["-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=2"]
        if self.target.user is not None:
            arguments += ["-l", self.target.user]
        return arguments

    def _environment(self) -> dict[str, str]:
        """Return the local environment for ssh; the handoff variables never reach the remote login."""
        environment = dict(subprocess_environment() or os.environ)
        environment.pop(CHILD_STATE_ENV, None)
        environment.pop(PLUGIN_ARGS_ENV, None)
        if self._askpass is not None:
            if self.password is None:
                raise RuntimeError(
                    "This SSH target signs in with a password, and no password is available here. "
                    "Passwords are never saved or inherited: open /ssh in the terminal and enter it again."
                )
            environment.update(self._askpass.environment(self.password))
        return environment

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
        environment = self._environment()
        self._process = await asyncio.create_subprocess_exec(
            "ssh",
            *self._ssh_arguments(),
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
        """Close the channel for good, forget the password, and refuse to reconnect.

        The cleanup is shielded from a second cancellation (a reader pressing Escape twice), exactly as a stuck
        request's is: the helper and the password must not outlive the close because the caller was interrupted.
        """
        self._closed = True

        async def closing() -> None:
            async with self._lock:
                await self._close()
                if self._askpass is not None:
                    self._askpass.close()
                self.password = None

        task = asyncio.create_task(closing())
        cancelled = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled = True
        task.result()
        if cancelled:
            raise asyncio.CancelledError

    @property
    def needs_password(self) -> bool:
        """Return whether this target signs in with a password that is not here (a restored target)."""
        return self.target.auth == "password" and self.password is None

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
            timeout = duration(arguments.get("timeout_seconds", 60)) if operation == "bash" else 120.0
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

                output = await asyncio.wait_for(exchange(), timeout + 15)
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
        timeout = duration(arguments.get("timeout_seconds", 60)) if operation == "bash" else 120.0
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
        environment = self._environment()
        process = await asyncio.create_subprocess_exec(
            "ssh",
            *self._ssh_arguments(),
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
            _, output, error, code = await asyncio.wait_for(asyncio.gather(*tasks), timeout=timeout + 15)
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
            result = response["result"]
            if operation == "read" and isinstance(result, dict):
                data = base64.b64decode(result["image"], validate=True)
                if len(data) > MAX_IMAGE or result["media_type"] not in {
                    "image/png",
                    "image/jpeg",
                    "image/gif",
                    "image/webp",
                }:
                    raise ValueError("Invalid remote image")
                return [
                    TextContent(text=f"Remote image {result['name']}: {result['media_type']}, {len(data)} bytes"),
                    ImageContent(
                        source=ImageBytesSource(data=data, media_type=result["media_type"]), alt_text=result["name"]
                    ),
                ]
            if not isinstance(result, str):
                raise ValueError("Invalid SSH tool result")
            return result
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
