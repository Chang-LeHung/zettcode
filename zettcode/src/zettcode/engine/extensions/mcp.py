"""The MCP extension ZettCode hands to the runtime: one broken server never stops the task.

zett-agent's :class:`McpExtension` connects the servers a configuration file names and registers
their tools. Two things used to make it brittle, and this module is about not letting either one
end a conversation:

* A server that would not start failed the whole request (zett-agent 0.1.14), and the failure
  named nothing. Since 0.1.15 the framework skips a server that cannot be reached or listed,
  carries on with the others, and tells *the model*. This adds the other half: it tells *the
  reader*, once, through the transcript, because a tool that quietly is not there looks like a
  bug in the program.
* One malformed entry in ``mcp.json`` invalidated the file, and a file that is not valid JSON
  failed the construction of the extension — which happens while the runtime is being built, so
  the first turn never ran. Entries that cannot be used are skipped and named, and a file that
  cannot be read at all means "no MCP servers" plus a line saying why.

* Starting a server is slow and silent. A stdio server is a process — ``npx`` may download a package
  first — and the framework connects and lists its tools while the first request waits, so the
  reader saw "Processing" for as long as that took with nothing to say why. A line is said when each
  server starts and when it is ready, with how long it took and how many tools it brought. A server
  whose tool list is already cached starts nothing, so it says nothing.

  That is said **once per session, at its first turn**: it explains why that turn was slow, and only
  that turn. The framework forgets a tool list after five minutes and lists it again at the top of the
  next request, which in a long conversation is most turns; a reader does not need to be told again
  each time that servers they already know about were looked at. A subagent, which has a session of its
  own beside the one the reader is in, says nothing: the reader never asked it anything.

A tool that fails while it runs is the framework's own business and already harmless: the failure
comes back to the model as an ordinary failed tool result, and the model carries on.

What this does *not* do is catch everything. A cancellation is how the reader stops a request, and
turning it into some other error would make Escape fail instead of stop; only ``Exception`` is
absorbed here.

The module is imported when a runtime starts, not when the application is imported: the MCP SDK it
builds on costs more than the first frame.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from contextvars import ContextVar
from pathlib import Path
from typing import Any, cast

from zett_agent.agent import AgentRunContext
from zett_agent.events import AgentEvent, AgentEventType
from zett_agent.extensions.mcp import DEFAULT_MCP_SERVER_KEYS, McpConfiguration, McpExtension, McpStdioServer

from zettcode.error_text import describe_error

from .mcp_notice import MCP_NOTICE_EVENT_NAME, notice_payload

#: The request whose tools are being discovered, so a server starting on its own task can say so in
#: that request's transcript. Set around the framework's discovery and read by the tasks it spawns, which
#: inherit it; ``None`` outside one.
_DISCOVERING: ContextVar[AgentRunContext | None] = ContextVar("zettcode_mcp_discovering", default=None)


class ReportingMcpExtension(McpExtension):
    """An MCP extension that keeps going when a server or a config entry is broken, and says so.

    Args:
        **options: Passed to :class:`McpExtension`. ``strict_config`` defaults to ``False`` here:
            the framework's default makes one bad entry invalidate every other server.
    """

    def __init__(self, **options: Any) -> None:
        options.setdefault("strict_config", False)
        super().__init__(**options)
        #: What each unavailable server was last reported as, so a server that stays down is
        #: reported once rather than at the top of every turn.
        self._reported: dict[str, str] = {}
        #: The stamp of the configuration file that was last checked for entries to report.
        self._checked: tuple[int, int] | None | object = _UNCHECKED
        #: Lines to say at the first request: what went wrong before there was a request to say it in.
        self.startup_issues: list[str] = []
        #: The sessions whose first turn has been and gone, which is when the start of the servers is said.
        self._narrated: set[str] = set()

    async def on_tool(self, context: AgentRunContext) -> None:
        """Register the tools of every server that works, and tell the reader about the ones that do not.

        An error the framework does not handle itself — it handles a server that cannot connect or
        list — costs this request its MCP tools and nothing else.
        """
        token = _DISCOVERING.set(context)
        try:
            await super().on_tool(context)
        except Exception as error:
            # Not BaseException: a cancellation has to stay a cancellation. The framework has
            # already closed what it opened for this request before the error got here.
            await self._say(context, f"MCP is unavailable for this request: {describe_error(error)}")
            return
        finally:
            _DISCOVERING.reset(token)
            # After the discovery, not before: every server of this turn is narrated or none is.
            if self._is_a_reader_session(context):
                self._narrated.add(cast(str, context.config.session_id))
        for line in (*self.startup_issues, *self._config_issues(), *self._server_issues(context)):
            await self._say(context, line)
        self.startup_issues.clear()

    async def _discover(self, request: Any, server: Any) -> Any:
        """Connect to one server and list its tools, saying when it starts and when it is ready.

        The framework's cache decides whether anything is started at all; when it holds this
        server's tools nothing is, and nothing is said. The server's command and arguments are
        never repeated here — they can carry a key — only its name and what kind of server it is.
        """
        context = _DISCOVERING.get()
        cached = self._tool_cache.get(server.name)
        starts = (
            context is not None
            and self._first_turn_of_a_reader_session(context)
            and not (cached is not None and cached.server == server and cached.expires_at > time.monotonic())
        )
        began = time.monotonic()
        if starts:
            kind = "process" if isinstance(server, McpStdioServer) else "connection"
            await self._say_quietly(context, f"Starting MCP server {server.name!r} ({kind})\u2026")
        tools = await super()._discover(request, server)
        if starts and tools is not None:
            count = len(tools)
            took = time.monotonic() - began
            noun = "tool" if count == 1 else "tools"
            await self._say_quietly(context, f"MCP server {server.name!r} is ready: {count} {noun}, {took:.1f}s")
        return tools

    @staticmethod
    def _is_a_reader_session(context: AgentRunContext) -> bool:
        """Return whether this request belongs to a session the reader is in, not to a subagent's own."""
        return not context.config.parent_session_id

    def _first_turn_of_a_reader_session(self, context: AgentRunContext) -> bool:
        """Return whether this is the first request its session has made, in a session the reader is in."""
        return self._is_a_reader_session(context) and cast(str, context.config.session_id) not in self._narrated

    async def _say_quietly(self, context: AgentRunContext | None, text: str, level: str = "info") -> None:
        """Say a line without letting the saying fail the discovery it reports on.

        These are progress lines (a server is starting, or ready), so they are ``info`` unless said otherwise.
        """
        if context is None:
            return
        try:
            await self._say(context, text, level)
        except Exception:  # noqa: BLE001 - news about a server must never be what stops it
            pass

    def _server_issues(self, context: AgentRunContext) -> list[str]:
        """Return a line for each server that became unavailable, or changed why, since last said.

        The framework keeps the reason on the request it made for this context and tells the model
        through the system prompt; neither is a way to ask it, so this reads the request. A server
        that works again is forgotten, so that its next failure is news.
        """
        request = self._requests.get(context)
        unavailable: dict[str, str] = dict(getattr(request, "unavailable", {}) or {})
        for name in [name for name in self._reported if name not in unavailable]:
            del self._reported[name]
        lines = []
        for name, reason in unavailable.items():
            if self._reported.get(name) != reason:
                self._reported[name] = reason
                lines.append(f"MCP server {name!r} is not available ({reason}); its tools are skipped until it works")
        return lines

    def _config_issues(self) -> list[str]:
        """Return a line for each entry of the configuration file that cannot be used.

        Checked when the file is first seen and again whenever it changes, not on every turn.
        """
        path = self.config_path
        if path is None:
            return []
        try:
            status = path.stat()
        except OSError:
            self._checked = None
            return []
        stamp = (status.st_mtime_ns, status.st_size)
        if stamp == self._checked:
            return []
        self._checked = stamp
        try:
            skipped = McpConfiguration.from_file(path, server_keys=self.server_keys, strict=False).skipped
        except (OSError, ValueError) as error:
            return [f"{path.name} cannot be used, so the last working MCP servers stay: {describe_error(error)}"]
        return [f"MCP server {name!r} in {path.name} is ignored: {reason}" for name, reason in skipped.items()]

    @staticmethod
    async def _say(context: AgentRunContext, text: str, level: str = "warn") -> None:
        """Publish one line for the transcript.

        A line is a warning unless it says otherwise: what reaches here from the checks (a server that is down, an
        entry that is ignored, a file that cannot be read) is something the reader may need to act on, and only the
        progress lines of a start say ``info``.
        """
        await context.emit(
            AgentEvent(
                type=AgentEventType.CUSTOM,
                session_id=cast(str, context.config.session_id),
                name=MCP_NOTICE_EVENT_NAME,
                payload=notice_payload(text, level),
            )
        )


#: Marks a stamp that has not been read yet, as distinct from a file that does not exist.
_UNCHECKED = object()


def build_mcp_extension(path: str | Path) -> ReportingMcpExtension:
    """Return the MCP extension for a server file, whatever state the file is in.

    The framework reads the file while the extension is constructed and raises when it is not
    valid JSON or names no servers. This runs while the runtime is being built, so letting that
    through would mean the first turn never starts because of a typo in a file the reader may not
    even remember. The extension is built with no servers instead, and the reason is said at the
    first request. Fixing the file takes effect on the next start: an extension that never loaded
    a good file has nothing to reload.

    Args:
        path: The server file the reader configured.
    """
    try:
        return ReportingMcpExtension(config_path=path)
    except (OSError, ValueError) as error:
        extension = ReportingMcpExtension(servers=())
        name = Path(path).name
        extension.startup_issues.append(
            f"{name} cannot be read, so MCP is off: {describe_error(error)}. Fix it and restart."
        )
        return extension


def build_scoped_mcp_extension(paths: Sequence[Path]) -> ReportingMcpExtension | None:
    """Return the MCP extension for the server files that exist, the first file winning a server name.

    One file is :func:`build_mcp_extension`, which also notices the file changing. Several are read
    once, here, and merged: the framework watches one path, and a server list assembled from two
    files has no single file to watch. A file that cannot be read costs only its own servers, and
    says why at the first request; an entry in it that cannot be used is named the same way.

    Args:
        paths: The files to read, the one that wins a name first; a path that is not a file is skipped.

    Returns:
        The extension, or ``None`` when no path is a file, so a run with nothing configured carries no
        MCP instructions at all.
    """
    present = [path for path in paths if path.is_file()]
    if not present:
        return None
    if len(present) == 1:
        return build_mcp_extension(present[0])
    servers: dict[str, Any] = {}
    issues: list[str] = []
    for path in present:
        label = f"{path.parent.name}/{path.name}"
        try:
            loaded = McpConfiguration.from_file(path, server_keys=DEFAULT_MCP_SERVER_KEYS, strict=False)
        except (OSError, ValueError) as error:
            issues.append(
                f"{label} cannot be read, so its servers are off: {describe_error(error)}. Fix it and restart."
            )
            continue
        issues.extend(f"MCP server {name!r} in {label} is ignored: {reason}" for name, reason in loaded.skipped.items())
        for server in loaded.servers:
            # The earlier file wins, so a project's server of the same name replaces the user's.
            servers.setdefault(server.name, server)
    extension = ReportingMcpExtension(servers=tuple(servers.values()))
    extension.startup_issues.extend(issues)
    return extension
