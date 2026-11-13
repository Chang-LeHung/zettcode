"""Codex and Claude Code as persistent gateway agents.

Each is an :class:`~zettcode.broker.external.ExternalSession` of its own whose handler runs the tool's own CLI.
The CLI's session id is kept in ``~/.zettcode/code-agents`` (or ``$ZETTCODE_CODE_AGENTS_DIR``), so the next message
continues the same conversation. The gateway only sees ordinary external sessions; nothing here re-implements a
model, a tool loop or a conversation store.

The commands can be changed without changing this package, and so can where the agents work and how far they are
trusted: see :mod:`zettcode.code_agents.config`. Those settings live in ``~/.zettcode/code-agents/config.json`` and are
read again for every message, so an edit applies to the next one with no restart. The environment variables still work
for the command itself:

* ``ZETTCODE_CODEX_ARGS`` / ``ZETTCODE_CODEX_RESUME_ARGS``
* ``ZETTCODE_CLAUDE_ARGS`` / ``ZETTCODE_CLAUDE_RESUME_ARGS``

They are split with :mod:`shlex` and receive ``{prompt}``, ``{session}`` and ``{cwd}``; they are never run by a shell.
The word ``{permission}`` on its own stands for the arguments of the trust level the settings choose.
"""

from __future__ import annotations

import asyncio
import base64
import json
import math
import os
import shlex
import signal
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from zettcode.broker.external import ExternalSession
from zettcode.broker.models import Incoming, Receipt
from zettcode.broker.protocol import KIND_EXTERNAL
from zettcode.code_agents.config import (
    PERMISSIONS,
    TIMEOUT,
    ConfigError,
    Settings,
    Tool,
    resolve,
    state_directory,
    work_directory,
)
from zettcode.gateway.agents import AgentField, AgentPlugin

#: The one place this plugin's version is written.
__version__ = "0.1.0"


def _timeout() -> float:
    """Return how long one turn may run without a setting, read from the environment and checked before use."""
    raw = os.environ.get("ZETTCODE_CODE_AGENTS_TIMEOUT", str(TIMEOUT))
    try:
        value = float(raw)
    except ValueError:
        raise RuntimeError(f"ZETTCODE_CODE_AGENTS_TIMEOUT must be a number of seconds, not {raw!r}") from None
    if not math.isfinite(value) or value <= 0:
        raise RuntimeError("ZETTCODE_CODE_AGENTS_TIMEOUT must be a positive number of seconds")
    return value


def _logo(name: str) -> str:
    """Return one of the package's brand marks as a data URL."""
    path = Path(__file__).with_name("logos") / name
    try:
        return "data:image/svg+xml;base64," + base64.b64encode(path.read_bytes()).decode()
    except OSError:
        return ""


@dataclass(frozen=True, slots=True)
class Command:
    """One tool's command line, new and resumed."""

    binary: str
    new_args: str
    resume_args: str

    def argv(
        self, prompt: str, session: str, cwd: Path, *, resume: bool = True, permission: tuple[str, ...] = ()
    ) -> list[str]:
        """Return the command to run. The word ``{permission}``, alone, becomes the arguments of the trust level.

        A template without that word is the person's own command line and is run exactly as written.
        """
        template = self.resume_args if resume and session and "{session}" in self.resume_args else self.new_args
        values = {"prompt": prompt, "session": session, "cwd": str(cwd)}
        argv = [self.binary]
        for part in shlex.split(template):
            if part == "{permission}":
                argv.extend(permission)
            else:
                argv.append(part.format(**values))
        return argv


@dataclass(frozen=True, slots=True)
class Launch:
    """What one turn runs with: the command, where, for how long, and the trust arguments for a new and a resumed turn."""

    command: Command
    cwd: Path
    timeout: float
    new_flags: tuple[str, ...]
    resume_flags: tuple[str, ...]


def _events(stdout: str) -> tuple[str, str]:
    """Return the last text and session id in a JSON or JSONL answer."""
    text = ""
    session = ""
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        for key in ("session_id", "thread_id"):
            value = event.get(key)
            if isinstance(value, str) and value:
                session = value
        for key in ("result", "text", "message", "content"):
            value = event.get(key)
            if isinstance(value, str) and value.strip():
                text = value
        item = event.get("item")
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            text = item["text"]
    return text, session


class CliAgent(ExternalSession):
    """An external session whose one handler runs a CLI and keeps its session id."""

    def __init__(
        self,
        session_id: str,
        title: str,
        source: Tool | Command,
        overrides: Mapping[str, str] | None = None,
    ) -> None:
        self._turns: set[asyncio.Task[None]] = set()
        self._limit = max(1, int(os.environ.get("ZETTCODE_CODE_AGENTS_QUEUE", "4")))
        super().__init__(session_id, title, kind=KIND_EXTERNAL, on_message=self._start_turn)
        #: A tool's settings are read again for every turn; a bare command (a caller's own) is run as it is given.
        self.source = source
        #: What the person chose for this one agent when starting it (``cwd``, ``permission``): it wins over the file.
        self.overrides = dict(overrides or {})
        self.state = state_directory() / f"{session_id}.json"
        self._lock = asyncio.Lock()
        self._process: asyncio.subprocess.Process | None = None

    def _start_turn(self, message: Incoming) -> Receipt:
        """Answer the broker now and run one CLI turn on a task."""
        if len(self._turns) >= self._limit:
            return Receipt(False, reason=f"{self.title} has {self._limit} turns waiting", busy=True)
        task = asyncio.ensure_future(self._turn(message))
        self._turns.add(task)
        task.add_done_callback(self._turns.discard)
        return Receipt(True, disposition="queued")

    async def _turn(self, message: Incoming) -> None:
        async with self._lock:
            await self.set_status("working")
            try:
                answer = await self._run(message.text)
            except Exception as error:  # noqa: BLE001 - the person gets the reason, the agent stays alive
                answer = f"{self.title} failed: {error}"
            finally:
                await self.set_status("idle")
            if message.group:
                await self.send_group(message.group, answer)
            else:
                await self.reply(message, answer)

    def _resolve(self) -> Launch:
        """Return what this turn runs with, read now: a person's edit of the settings applies from the next message."""
        source = self.source
        if isinstance(source, Command):
            return Launch(source, work_directory(), _timeout(), (), ())
        settings: Settings = resolve(source, timeout=_timeout(), overrides=self.overrides)
        command = Command(settings.binary, settings.args, settings.resume_args)
        return Launch(
            command,
            settings.cwd,
            settings.timeout,
            source.flags[settings.permission],
            source.resume_flags[settings.permission],
        )

    async def _run(self, prompt: str) -> str:
        launch = self._resolve()
        command, timeout = launch.command, launch.timeout
        session = self._session()
        resumed = bool(session)
        if not session and "session-id" in command.new_args:
            session = str(uuid.uuid4())
        # The trust arguments follow the template that is used: a resume template without {session} is the new one.
        continuing = resumed and "{session}" in command.resume_args
        argv = command.argv(
            prompt,
            session,
            launch.cwd,
            resume=resumed,
            permission=launch.resume_flags if continuing else launch.new_flags,
        )
        options: dict[str, Any] = {}
        if os.name != "nt":
            options["start_new_session"] = True
        self._process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(launch.cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **options,
        )
        process = self._process
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
        except asyncio.TimeoutError:
            self._kill(process)
            await process.wait()
            raise RuntimeError(f"the {self.title} command did not finish in {timeout:g} seconds") from None
        finally:
            self._process = None
        output = stdout.decode(errors="replace")
        error = stderr.decode(errors="replace").strip()
        if process.returncode not in (None, 0):
            raise RuntimeError(error or f"exit code {process.returncode}")
        text, found = _events(output)
        if found:
            self._save(found)
        if text:
            return text
        if output.strip():
            return output.strip()
        raise RuntimeError(error or "the command said nothing")

    async def close(self) -> None:
        """Stop a running CLI process before closing the session."""
        process, self._process = self._process, None
        tasks, self._turns = list(self._turns), set()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if process is not None and process.returncode is None:
            self._kill(process)
            await process.wait()
        await super().close()

    @staticmethod
    def _kill(process: asyncio.subprocess.Process) -> None:
        """Kill the CLI and the children it forked, when the platform gives the process a session."""
        if os.name == "nt":
            process.kill()
            return
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            process.kill()

    def _session(self) -> str:
        try:
            data = json.loads(self.state.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return ""
        value = data.get("session") if isinstance(data, dict) else None
        return value if isinstance(value, str) else ""

    def _save(self, session: str) -> None:
        self.state.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state.with_suffix(".tmp")
        temporary.write_text(json.dumps({"session": session}), encoding="utf-8")
        os.replace(temporary, self.state)


_CODEX_FULL = ("--dangerously-bypass-approvals-and-sandbox",)

#: Codex. ``exec`` takes ``--sandbox``; ``exec resume`` does not, and takes the same choice as a config override.
CODEX = Tool(
    name="codex",
    env="ZETTCODE_CODEX",
    binary="codex",
    args="exec --json --skip-git-repo-check {permission} {prompt}",
    resume_args="exec resume {session} --json {permission} {prompt}",
    flags={
        "full": _CODEX_FULL,
        "workspace": ("--sandbox", "workspace-write"),
        "read": ("--sandbox", "read-only"),
    },
    resume_flags={
        "full": _CODEX_FULL,
        "workspace": ("-c", 'sandbox_mode="workspace-write"'),
        "read": ("-c", 'sandbox_mode="read-only"'),
    },
)

_CLAUDE_FLAGS = {
    "full": ("--permission-mode", "bypassPermissions"),
    "workspace": ("--permission-mode", "acceptEdits"),
    "read": ("--permission-mode", "plan"),
}

#: Claude Code, which takes the same ``--permission-mode`` for a new conversation and a resumed one.
CLAUDE = Tool(
    name="claude",
    env="ZETTCODE_CLAUDE",
    binary="claude",
    args="{permission} -p {prompt} --output-format json --session-id {session}",
    resume_args="{permission} -p {prompt} --output-format json --resume {session}",
    flags=_CLAUDE_FLAGS,
    resume_flags=_CLAUDE_FLAGS,
)


#: What the page may choose for a code agent when it starts one. Left empty, the settings file (and then the defaults)
#: apply, so an agent started with no choice behaves as before.
FIELDS = (
    AgentField(
        "cwd",
        "Folder",
        kind="directory",
        help="The folder the agent works in. Left empty, the one in the settings file, or the plugin's own folder.",
    ),
    AgentField(
        "permission",
        "Access",
        kind="choice",
        choices=PERMISSIONS,
        help="full: no sandbox and no approval. workspace: may change files in its folder. read: may only read.",
        unrestricted="full",
    ),
)


class CodexAgent(AgentPlugin):
    name = CODEX.name
    title = "Codex"
    description = "OpenAI Codex CLI, in the same session every time"
    avatar = _logo("codex.svg")
    fields = FIELDS

    def create(self, session_id: str, title: str) -> ExternalSession:
        return CliAgent(session_id, title, CODEX)

    def create_with(self, session_id: str, title: str, options: Mapping[str, str]) -> ExternalSession:
        return CliAgent(session_id, title, CODEX, options)


class ClaudeCodeAgent(AgentPlugin):
    name = CLAUDE.name
    title = "Claude Code"
    description = "Anthropic Claude Code, in the same session every time"
    avatar = _logo("claude.svg")
    fields = FIELDS

    def create(self, session_id: str, title: str) -> ExternalSession:
        return CliAgent(session_id, title, CLAUDE)

    def create_with(self, session_id: str, title: str, options: Mapping[str, str]) -> ExternalSession:
        return CliAgent(session_id, title, CLAUDE, options)


__all__ = [
    "CLAUDE",
    "CODEX",
    "ClaudeCodeAgent",
    "CliAgent",
    "CodexAgent",
    "Command",
    "ConfigError",
    "Launch",
    "state_directory",
    "work_directory",
]
