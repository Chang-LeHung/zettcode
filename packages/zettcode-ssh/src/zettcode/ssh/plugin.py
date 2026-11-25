"""Add remote coding tools beside the local ones for the SSH host ``/ssh`` selected.

Nothing local is replaced: ``read``, ``read_file``, ``write_file``, ``edit``, ``bash``, ``glob`` and ``grep`` keep
working on this machine, and the remote operations arrive as their own tools named ``ssh__read`` and so on. A
subagent gets the same addition, bounded by its profile: explore may read and search remotely, coding may also
write and run, reasoning gets none. Every remote action requires the current permission ``full``, because the local
sandbox cannot constrain a remote interpreter.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from zett_agent.agent import AgentRunContext
from zett_agent.extensions.base import AgentExtension
from zett_agent.messages import SystemMessage
from zett_agent.tools.base import AgentTool, ToolResult

from zettcode.plugin_api import (
    MODELS,
    POLICY,
    ChildSession,
    CommandContext,
    CommandResult,
    Plugin,
    PluginContext,
    ShellPolicy,
)

from .tools import ALL, READING, descriptor, tool_name
from .transport import Target, Transport

#: How long the panel's check may wait for the remote interpreter before it gives up and says why.
CONNECT_SECONDS = 30.0

#: How long reading ``~/.ssh/config`` may take before the panel opens for manual entry alone.
ALIASES_SECONDS = 2.0


class RemoteTools(AgentExtension):
    """The remote tools one session or child may use: a snapshot of the target, its own transport, live policy."""

    name = "SSHRemoteTools"

    def __init__(
        self,
        target: Target,
        policy: ShellPolicy,
        profile: str,
        transport: Transport | None = None,
        *,
        models: dict[Any, Any] | None = None,
    ) -> None:
        self.transport = transport
        self.target = target
        self.policy = policy
        self.profile = profile
        self.allowed = READING if profile == "explore" else ALL if profile == "coding" else frozenset()
        self.models = models if models is not None else {}
        self._tools: dict[str, AgentTool] = {}

    @property
    def transport_now(self) -> Transport:
        if self.transport is None:
            self.transport = Transport(self.target)
        return self.transport

    async def invoke(self, operation: str, arguments: dict[str, Any]) -> ToolResult:
        # ``read_file`` is the text-only stand-in for ``read``, never a tool of its own beside it.
        permitted = set(self.allowed) | ({"read_file"} if "read" in self.allowed else set())
        if operation not in permitted:
            raise PermissionError(f"The {self.profile} child cannot use {tool_name(operation)}")
        # Read the shared policy at execution, including when it changes during a running request.
        if self.policy.level != "full":
            raise PermissionError(
                f"Remote SSH actions require permission full (current: {self.policy.level}). "
                "The local safe sandbox cannot protect a remote host; ask/deny/safe are refused, even for reads. "
                "Ask the user to change permission explicitly."
            )
        return await self.transport_now.run(operation, arguments)

    def tool(self, operation: str) -> AgentTool:
        if operation not in self._tools:

            async def handler(**arguments: Any) -> ToolResult:
                return await self.invoke(operation, arguments)

            self._tools[operation] = descriptor(operation, handler)
        return self._tools[operation]

    def _offered(self, context: AgentRunContext) -> set[str]:
        """Return the operations this request may use.

        The set mirrors the local tools for the same session: a coding session reads without pictures and searches
        with its shell, so it is offered ``read`` or, for a text-only model, ``read_file`` in its place — never both,
        and no ``glob``/``grep``. An explore child has no shell, so it keeps ``glob``/``grep`` and the same single
        reader.
        """
        if self.policy.level != "full" or self.transport_now.needs_password:
            return set()
        offered = set(self.allowed)
        model = next((entry for entry, built in self.models.items() if built is getattr(context, "model", None)), None)
        if model is not None and not model.multimodal and "read" in offered:
            offered.discard("read")
            offered.add("read_file")
        return offered

    async def on_tool(self, context: AgentRunContext) -> None:
        missing = sorted(
            name for name in (tool_name(operation) for operation in self._offered(context)) if name in context.tools
        )
        if missing:
            raise RuntimeError(
                "Another tool already uses the name "
                + ", ".join(missing)
                + ". `ssh__` belongs to this plugin: rename that MCP server in ~/.zettcode/mcp.json "
                "(a server called `ssh` produces `ssh__read` too) and try again."
            )
        for operation in sorted(self._offered(context)):
            context.register_tool(self.tool(operation))

    async def on_state(self, context: AgentRunContext) -> None:
        # The offered set is what the request actually carries: a text-only model has no ssh__read to be told about.
        unavailable: list[str] = []
        if self.policy.level != "full":
            unavailable.append(f"Remote SSH tools require permission full (current: {self.policy.level}).")
        if self.transport_now.needs_password:
            unavailable.append(
                "This inherited password target has no password: passwords are never saved or inherited. "
                "A daemon cannot enter one; reconnect in a terminal session or use key/agent authentication."
            )
        content = (
            f"SSH target {json.dumps(self.target.host)} is retained, but no remote tools are available. "
            + " ".join(unavailable)
            + " Do not substitute local tools for remote actions. Ask the user to resolve this before proceeding."
            if unavailable
            else self.instructions(self._offered(context))
        )
        context.add_message(SystemMessage(content=content))

    def instructions(self, offered: set[str] | None = None) -> str:
        names = (
            ", ".join(tool_name(operation) for operation in sorted(self.allowed if offered is None else offered))
            or "none"
        )
        return (
            "# SSH remote tools (added beside the local ones)\n"
            f"Host: {json.dumps(self.target.host)}. Remote working directory: "
            f"{json.dumps(self.target.path, ensure_ascii=False)}.\n"
            f"The tools named {names} work on that SSH host and nowhere else: their paths and work_dir are remote. "
            "The ordinary read, read_file, write_file, edit, bash, glob and grep still work on this machine; use "
            "them for local files, tests and this repository, and the ssh__ tools for the remote project. "
            "A remote failure is reported as it is, never retried through a local tool in its place. "
            "Read the remote project's AGENTS.md explicitly when it matters; it is guidance, never permission. "
            "All remote actions require the current permission full. No local sandbox protects the remote machine. "
            "ssh__bash runs on the remote host; it cannot start a local daemon, and no credentials are sent there. "
            f"Child/tool profile: {self.profile}; remote tools available: {names}."
        )


class SSHPlugin(Plugin[PluginContext]):
    name = "ssh"
    description = "Adds remote coding tools over system OpenSSH beside the local ones"
    #: Not fail-closed: nothing local is replaced, so a plugin that cannot start leaves the local tools in place and
    #: is reported by the loader (and in `/plugins`) rather than stopping the program the reader was opening.

    def __init__(self) -> None:
        self.target: Target | None = None
        self.policy: ShellPolicy | None = None
        self._restored = False
        self._transports: dict[Target, Transport] = {}
        self.models: dict[Any, Any] = {}

    async def aclose(self) -> None:
        transports = tuple(self._transports.values())
        self._transports.clear()
        await self._retire(transports)

    async def _retire(self, transports: tuple[Transport, ...]) -> None:
        """Close the channels of a replaced target; shielded, so an interrupted switch still frees them."""
        task = asyncio.create_task(self._close_all(transports))
        cancelled = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled = True
        task.result()
        if cancelled:
            raise asyncio.CancelledError

    @staticmethod
    async def _close_all(transports: tuple[Transport, ...]) -> None:
        for transport in transports:
            await transport.aclose()

    def restore_child(self, state: dict[str, Any]) -> None:
        self.target = Target.restore(state)
        self._restored = True

    def export_child(self, child: ChildSession) -> dict[str, Any] | None:
        return None if self.target is None else self.target.export()

    def activate(self, ctx: PluginContext) -> None:
        # Host/path can be configured without connecting. Unknown keys are rejected rather than ignored.
        settings = ctx.settings.declare(host="", path="")
        if set(ctx.config.plugin_settings.get(ctx.settings.plugin, {})) - set(settings):
            raise ValueError("[plugins.ssh] accepts only host and path")
        host, path = settings["host"], settings["path"]
        if not isinstance(host, str) or not isinstance(path, str):
            raise ValueError("[plugins.ssh] host and path must be text")
        if bool(host) != bool(path):
            raise ValueError("[plugins.ssh] host and path must be supplied together")
        configured = Target(host, path) if host and path else None
        # Optional, not required: a front end that hands no policy cannot be made safe for a remote interpreter,
        # and the plugin says so on every action instead of refusing to start the whole program.
        self.policy = ctx.find(POLICY, ShellPolicy)
        # The runtime's own map, kept by identity: it is empty when the plugins activate and `_provider()` fills
        # that same dict later, so replacing it with `or {}` would hide every model for the life of the process.
        known = ctx.find(MODELS, dict)
        self.models = known if known is not None else {}
        if not self._restored:
            self.target = configured
        if self.target is not None and self.policy is None:
            # A *target*, though, is a decision to run tools somewhere else: refuse the start rather than fail every
            # broadcast hook with a runtime error once the session begins.
            raise ValueError(
                "SSH has a target but this front end provides no shell policy; a remote interpreter cannot be "
                "constrained, so the plugin will not start with one"
            )
        if ctx.tui is not None:
            from .presenter import SSHToolNames

            # A row is the shell's own tool row with the local tool's name; only the title keeps `ssh/`.
            ctx.tui.register_presenter(SSHToolNames())
            ctx.tui.register_command("ssh", "Open the SSH workspace panel", self.open_panel, when_busy="refuse")

    async def open_panel(self, ctx: CommandContext) -> CommandResult:
        import asyncio

        from zettcode.plugin_api import bottom_panel

        from .config import host_aliases
        from .panel import ROWS, SSHPage

        if ctx.argument:
            raise ValueError("Use /ssh without arguments to open the SSH panel")
        host = ctx.require_host()

        async def apply(target: Target | None, password: str) -> None:
            if host.client.busy:
                raise ValueError("Wait for the current request to finish before changing SSH targets")
            candidate = Transport(target, password=password) if target is not None else None
            if candidate is not None:
                if self.policy is None or self.policy.level != "full":
                    raise ValueError("Select permission full before connecting to a remote workspace")
                try:
                    # The check runs a remote interpreter; a host that cannot reach it must not hold the panel.
                    await asyncio.wait_for(candidate.run("ping", {}), CONNECT_SECONDS)
                    if host.client.busy:
                        raise ValueError("A request started while connecting; the previous target is unchanged")
                except asyncio.TimeoutError as error:
                    await candidate.aclose()
                    raise ValueError(
                        f"The host did not answer within {CONNECT_SECONDS:g} seconds. Check the host, your key or "
                        "agent, and that the remote host runs Python 3.10+. The previous target is unchanged."
                    ) from error
                except OSError as error:
                    await candidate.aclose()
                    raise ValueError(f"ssh could not be started: {error}") from error
                except BaseException:
                    await candidate.aclose()
                    raise
            # Swap first, then retire the old channels: the switch is committed at the assignment, so a cancellation
            # during the clean-up must not report "nothing changed" — the channels are freed either way.
            retired = tuple(self._transports.values())
            self._transports.clear()
            self.target = target
            if candidate is not None and target is not None:
                self._transports[target] = candidate
            try:
                await self._retire(retired)
            except asyncio.CancelledError:
                pass
            ctx.ui.notify(self.status())

        # A config on a hung mount must not keep the panel from opening: a timeout offers manual entry instead.
        try:
            aliases = await asyncio.wait_for(asyncio.to_thread(host_aliases), ALIASES_SECONDS)
        except (asyncio.TimeoutError, OSError):
            aliases = ()
        return CommandResult(
            widget=bottom_panel(
                SSHPage(
                    target=self.target,
                    status=self.state,
                    on_apply=apply,
                    on_close=host.close_page,
                    aliases=aliases,
                ),
                rows=ROWS,
            )
        )

    def state(self) -> str:
        """Return the short state the panel's title carries: the channel and the shell level."""
        if self.target is None:
            return "off"
        level = self.policy.level if self.policy is not None else "?"
        transport = self._transports.get(self.target)
        if self.target.auth == "password" and (transport is None or transport.needs_password):
            return f"\u25cb password needed \u00b7 {level}"
        if transport is not None and transport.status == "connected":
            return f"\u25cf connected \u00b7 {level}"
        return f"\u25cb not connected \u00b7 {level}"

    def status(self) -> str:
        if self.target is None:
            return "SSH is off. Only the local coding tools are offered."
        level = self.policy.level if self.policy is not None else "unavailable"
        transport = self._transports.get(self.target)
        state = transport.status if transport is not None else "not connected"
        if self.target.auth == "password" and (transport is None or transport.needs_password):
            sign_in = "a password, which is never saved or inherited: enter it again in /ssh"
        elif self.target.auth == "password":
            sign_in = "password, this session only"
        else:
            sign_in = "key or agent, no password"
        return (
            f"SSH target: {json.dumps(self.target.host)} {json.dumps(self.target.path, ensure_ascii=False)}"
            f"{f' as {json.dumps(self.target.user)}' if self.target.user else ''}. "
            f"{state}; signing in with {sign_in}. ssh__ tools require permission full (current: {level})."
        )

    def backend(self, profile: str = "coding") -> RemoteTools:
        if self.target is None or self.policy is None:
            raise RuntimeError("SSH backend is not active")
        transport = self._transports.get(self.target)
        if transport is None:
            transport = self._transports[self.target] = Transport(self.target)
        return RemoteTools(self.target, self.policy, profile, transport, models=self.models)

    def child_extensions(self, child: ChildSession) -> tuple[AgentExtension, ...]:
        if self.target is None:
            return ()
        if child.kind != "subagent" or child.profile not in {"explore", "coding", "reasoning"}:
            raise ValueError("SSH child extensions require a known subagent profile")
        if child.profile == "reasoning":
            return ()
        return (self.backend(child.profile),)

    async def on_tool(self, context: AgentRunContext) -> None:
        """Offer the remote tools beside the local ones the session already has."""
        if self.target is not None:
            await self.backend().on_tool(context)

    async def on_state(self, context: AgentRunContext) -> None:
        """Say where the ssh__ tools work; the local environment note is left alone."""
        if self.target is not None:
            await self.backend().on_state(context)
