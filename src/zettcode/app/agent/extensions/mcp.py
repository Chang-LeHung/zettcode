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

A tool that fails while it runs is the framework's own business and already harmless: the failure
comes back to the model as an ordinary failed tool result, and the model carries on.

What this does *not* do is catch everything. A cancellation is how the reader stops a request, and
turning it into some other error would make Escape fail instead of stop; only ``Exception`` is
absorbed here.

The module is imported when a runtime starts, not when the application is imported: the MCP SDK it
builds on costs more than the first frame.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from zett_agent.agent import AgentRunContext
from zett_agent.events import AgentEvent, AgentEventType
from zett_agent.extensions.mcp import McpConfiguration, McpExtension

from ..errors import describe_error
from .mcp_notice import MCP_NOTICE_EVENT_NAME, notice_payload


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

    async def on_tool(self, context: AgentRunContext) -> None:
        """Register the tools of every server that works, and tell the reader about the ones that do not.

        An error the framework does not handle itself — it handles a server that cannot connect or
        list — costs this request its MCP tools and nothing else.
        """
        try:
            await super().on_tool(context)
        except Exception as error:
            # Not BaseException: a cancellation has to stay a cancellation. The framework has
            # already closed what it opened for this request before the error got here.
            await self._say(context, f"MCP is unavailable for this request: {describe_error(error)}")
            return
        for line in (*self.startup_issues, *self._config_issues(), *self._server_issues(context)):
            await self._say(context, line)
        self.startup_issues.clear()

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
    async def _say(context: AgentRunContext, text: str) -> None:
        """Publish one line for the transcript."""
        await context.emit(
            AgentEvent(
                type=AgentEventType.CUSTOM,
                session_id=cast(str, context.config.session_id),
                name=MCP_NOTICE_EVENT_NAME,
                payload=notice_payload(text),
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
