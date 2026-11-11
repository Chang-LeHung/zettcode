"""Codex and Claude Code as persistent gateway agents.

Each is an :class:`~zettcode.broker.external.ExternalSession` of its own whose handler runs the tool's own CLI.
The CLI's session id is kept in ``~/.zettcode/code-agents`` (or ``$ZETTCODE_CODE_AGENTS_DIR``), so the next message
continues the same conversation. The gateway only sees ordinary external sessions; nothing here re-implements a
model, a tool loop or a conversation store.

The commands can be changed without changing this package:

* ``ZETTCODE_CODEX_ARGS`` / ``ZETTCODE_CODEX_RESUME_ARGS``
* ``ZETTCODE_CLAUDE_ARGS`` / ``ZETTCODE_CLAUDE_RESUME_ARGS``

They are split with :mod:`shlex` and receive ``{prompt}``, ``{session}`` and ``{cwd}``; they are never run by a shell.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import shlex
import uuid
from dataclasses import dataclass
from pathlib import Path

from zettcode.broker.external import ExternalSession
from zettcode.broker.models import Incoming
from zettcode.broker.protocol import KIND_ZETTCODE
from zettcode.gateway.agents import AgentPlugin

#: How long one CLI turn may take before it is stopped.
TIMEOUT = 900.0


def _logo(mark: str, background: str, foreground: str) -> str:
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        f'<rect width="64" height="64" rx="16" fill="{background}"/>'
        f'<text x="32" y="40" text-anchor="middle" font-family="ui-monospace,monospace" '
        f'font-size="24" font-weight="700" fill="{foreground}">{mark}</text></svg>'
    )
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def state_directory() -> Path:
    """Return where the CLI session ids are kept."""
    return Path(os.environ.get("ZETTCODE_CODE_AGENTS_DIR", str(Path.home() / ".zettcode" / "code-agents"))).expanduser()


def work_directory() -> Path:
    """Return the directory the CLI runs in."""
    return Path(os.environ.get("ZETTCODE_CODE_AGENTS_CWD", str(Path.cwd()))).expanduser()


@dataclass(frozen=True, slots=True)
class Command:
    """One tool's command line, new and resumed."""

    binary: str
    new_args: str
    resume_args: str

    def argv(self, prompt: str, session: str, cwd: Path, *, resume: bool = True) -> list[str]:
        template = self.resume_args if resume and session and "{session}" in self.resume_args else self.new_args
        values = {"prompt": prompt, "session": session, "cwd": str(cwd)}
        return [self.binary, *(part.format(**values) for part in shlex.split(template))]


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

    def __init__(self, session_id: str, title: str, command: Command) -> None:
        super().__init__(session_id, title, kind=KIND_ZETTCODE)
        self.command = command
        self.cwd = work_directory()
        self.state = state_directory() / f"{session_id}.json"
        self._lock = asyncio.Lock()
        self._process: asyncio.subprocess.Process | None = None

    async def on_message(self, message: Incoming) -> str:
        """Run one CLI turn and return its last words; the session wrapper sends them back."""
        async with self._lock:
            await self.set_status("working")
            try:
                return await self._run(message.text)
            except Exception as error:  # noqa: BLE001 - the person gets the reason, the agent stays alive
                return f"{self.title} failed: {error}"
            finally:
                await self.set_status("idle")

    async def _run(self, prompt: str) -> str:
        session = self._session()
        resumed = bool(session)
        if not session and "session-id" in self.command.new_args:
            session = str(uuid.uuid4())
        argv = self.command.argv(prompt, session, self.cwd, resume=resumed)
        self._process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(self.cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        process = self._process
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), TIMEOUT)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            raise RuntimeError(f"the {self.title} command did not finish in {TIMEOUT:g} seconds") from None
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
        if process is not None and process.returncode is None:
            process.kill()
            await process.wait()
        await super().close()

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


class CodexAgent(AgentPlugin):
    name = "codex"
    title = "Codex"
    description = "OpenAI Codex CLI, in the same session every time"
    avatar = _logo(">_", "#0b0b0f", "#ffffff")

    def create(self, session_id: str, title: str) -> ExternalSession:
        return CliAgent(
            session_id,
            title,
            Command(
                os.environ.get("ZETTCODE_CODEX_BIN", "codex"),
                os.environ.get("ZETTCODE_CODEX_ARGS", "exec --json --skip-git-repo-check {prompt}"),
                os.environ.get("ZETTCODE_CODEX_RESUME_ARGS", "exec resume {session} --json {prompt}"),
            ),
        )


class ClaudeCodeAgent(AgentPlugin):
    name = "claude"
    title = "Claude Code"
    description = "Anthropic Claude Code, in the same session every time"
    avatar = _logo("✳", "#d97757", "#ffffff")

    def create(self, session_id: str, title: str) -> ExternalSession:
        return CliAgent(
            session_id,
            title,
            Command(
                os.environ.get("ZETTCODE_CLAUDE_BIN", "claude"),
                os.environ.get("ZETTCODE_CLAUDE_ARGS", "-p {prompt} --output-format json --session-id {session}"),
                os.environ.get("ZETTCODE_CLAUDE_RESUME_ARGS", "-p {prompt} --output-format json --resume {session}"),
            ),
        )


__all__ = ["ClaudeCodeAgent", "CodexAgent", "Command", "CliAgent", "state_directory", "work_directory"]
