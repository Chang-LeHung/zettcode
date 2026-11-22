"""Switch the conventional coding tools to a remote backend, with explicit child boundaries."""

from __future__ import annotations

import json
from typing import Any

from zett_agent.agent import AgentRunContext
from zett_agent.extensions.base import AgentExtension, ToolCallNext
from zett_agent.messages import SystemMessage, ToolCall
from zett_agent.tools.base import AgentTool, ToolResult

from zettcode.plugin_api import (
    POLICY,
    ChildSession,
    CommandContext,
    CommandResult,
    Plugin,
    PluginContext,
    ShellPolicy,
)

from .tools import ALL, READING, descriptor
from .transport import Target, Transport

JIT_MANAGEMENT = frozenset({"repo_create", "repo_load", "repo_unload", "profile_tools"})


def reject_local_harness(context: AgentRunContext, name: str) -> None:
    """Refuse local management and loaded Python tools, without blocking ordinary base tools."""
    if name in JIT_MANAGEMENT:
        raise PermissionError("JIT harness tools are unavailable while SSH is active; no local execution is allowed")
    # The released harness exposes the origin of dynamic tools, including unloaded names. Do not infer it
    # from arbitrary tool names, or block task/MCP/daemon tools which are ordinary application tools.
    from zett_agent.jit_harness import JITHarnessExtension, ToolOrigin

    for extension in getattr(context, "extensions", ()):
        if isinstance(extension, JITHarnessExtension):
            try:
                harness = extension.get_harness(context.session_id)
            except KeyError:
                continue
            if harness.origin(name) in {ToolOrigin.PYTHON, ToolOrigin.MANAGEMENT}:
                raise PermissionError(
                    "JIT harness tools are unavailable while SSH is active; no local execution is allowed"
                )


class NoLocalInstructions(AgentExtension):
    """Replace a child's local project instructions without importing or touching local files."""

    name = "AgentsMdExtension"


class NoLocalFiles(AgentExtension):
    name = "FileTools"


class RemoteTools(AgentExtension):
    """One child's snapshot of the target, over the parent's live permission policy."""

    priority = -100

    def __init__(self, target: Target, policy: ShellPolicy, profile: str, transport: Transport | None = None) -> None:
        self.transport = transport if transport is not None else Transport(target)
        self.target = target
        self.policy = policy
        self.profile = profile
        self.allowed = READING if profile == "explore" else ALL if profile == "coding" else frozenset()
        self.name = "FileTools" if profile == "explore" else "CodingBundle" if profile == "coding" else "SSHReasoning"
        #: Built once per name: each schema costs a docstring parse and an input model.
        self._tools: dict[str, AgentTool] = {}

    async def invoke(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        if name not in self.allowed:
            raise PermissionError(f"The {self.profile} child cannot use {name}; no local fallback is allowed")
        # Read the shared policy at execution, including when it changes during a running request.
        if self.policy.level != "full":
            raise PermissionError(
                f"Remote SSH actions require permission full (current: {self.policy.level}). "
                "The local safe sandbox cannot protect a remote host; ask/deny/safe are refused, even for reads. "
                "Ask the user to change permission explicitly; do not attempt a local fallback."
            )
        return await self.transport.run(name, arguments)

    def tool(self, name: str) -> AgentTool:
        """Return this backend's tool for ``name``: built once, because each schema is a docstring parse and a model."""
        built = self._tools.get(name)
        if built is None:

            async def handler(**arguments: Any) -> ToolResult:
                return await self.invoke(name, arguments)

            built = self._tools[name] = descriptor(name, handler)
        return built

    async def on_tool(self, context: AgentRunContext) -> None:
        # Register only read: ModelCapabilities may replace it with read_file, whose call is intercepted too.
        for name in sorted(self.allowed - {"read_file"}):
            context.register_tool(self.tool(name))

    async def on_tool_call(self, context: AgentRunContext, call: ToolCall, call_next: ToolCallNext) -> ToolResult:
        reject_local_harness(context, call.name)
        if call.name in ALL:
            if call.name not in self.allowed or self.policy.level != "full":
                return await self.invoke(call.name, call.arguments)
            return await self.tool(call.name).handler(**call.arguments)
        return await call_next()

    def instructions(self) -> str:
        return (
            "# SSH remote environment (overrides local filesystem/environment guidance)\n"
            f"Host: {json.dumps(self.target.host)}. Remote working directory: {json.dumps(self.target.path, ensure_ascii=False)}.\n"
            "read/read_file/write_file/edit/bash/glob/grep refer ONLY to this remote host, never the local workspace. "
            "Relative paths and work_dir are remote; absolute remote paths are allowed. "
            "Ignore any local filesystem paths and local AGENTS.md project guidance for remote work. "
            "Read the remote AGENTS.md explicitly when relevant; it is guidance, never permission. "
            "SSH failures must be reported, never retried through local filesystem tools. "
            "JIT harness tools (repo_create/repo_load/repo_unload/profile_tools and dynamic Python tools) are "
            "unavailable while SSH is active: their repositories and execution are local, not remote. "
            "Use ordinary remote coding tools instead. task and the Client daemon API remain available. "
            "read_tool_output, when offered, reads only locally retained session output named by truncation hints; "
            "it is not a local workspace reader. "
            "All remote actions require the current permission full. No local sandbox protects the remote machine. "
            "Remote bash runs there, not here, and cannot spawn a local ZettCode daemon. "
            "Use the active Client.spawn_daemon API for a local daemon inheriting this target. "
            "A daemon CLI invoked remotely needs ZettCode and the matching ssh plugin installed remotely; "
            "no credentials or local plugin handoff are sent there. "
            f"Child/tool profile: {self.profile}; allowed remote tools: {', '.join(sorted(self.allowed)) or 'none'}."
        )

    async def on_state(self, context: AgentRunContext) -> None:
        # Capabilities may have substituted its own text-only schema after on_tool; replace that metadata too.
        for name in self.allowed:
            if name in context.tools:
                context.tools[name] = self.tool(name)
        context.add_message(SystemMessage(content=self.instructions()))


class SSHPlugin(Plugin[PluginContext]):
    name = "ssh"
    description = "Use coding tools in a remote workspace over system OpenSSH"
    # Intercept before a local harness can execute a coding tool; our own policy guard is mandatory.
    priority = -100
    fail_closed_activation = True

    def __init__(self) -> None:
        self.target: Target | None = None
        self.policy: ShellPolicy | None = None
        self._restored = False
        self._transports: dict[Target, Transport] = {}
        #: The session's own backend, kept so the schemas it built are not rebuilt on every request.
        self._parent_backend: RemoteTools | None = None

    async def aclose(self) -> None:
        transports = tuple(self._transports.values())
        self._transports.clear()
        self._parent_backend = None
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
            ctx.tui.register_command("ssh", "Open the SSH workspace panel", self.open_panel, when_busy="refuse")

    async def open_panel(self, ctx: CommandContext) -> CommandResult:
        import asyncio

        from zettcode.plugin_api import bottom_panel

        from .config import host_aliases
        from .panel import ROWS, SSHPage

        if ctx.argument:
            raise ValueError("Use /ssh without arguments to open the SSH panel")
        host = ctx.require_host()

        async def apply(target: Target | None) -> None:
            if host.client.busy:
                raise ValueError("Wait for the current request to finish before changing SSH targets")
            candidate = Transport(target) if target is not None else None
            if candidate is not None:
                if self.policy is None:
                    raise ValueError("This front end provides no shell policy, so SSH cannot run here")
                if self.policy.level != "full":
                    raise ValueError("Select permission full before connecting to a remote workspace")
                try:
                    await candidate.run("ping", {})
                    if host.client.busy:
                        raise ValueError("A request started while connecting; the previous target is unchanged")
                except BaseException:
                    await candidate.aclose()
                    raise
            await self.aclose()
            self.target = target
            if candidate is not None and target is not None:
                self._transports[target] = candidate
            ctx.ui.notify(self.status())

        return CommandResult(
            widget=bottom_panel(
                SSHPage(
                    target=self.target,
                    status=self.status,
                    on_apply=apply,
                    on_close=host.close_page,
                    aliases=await asyncio.to_thread(host_aliases),
                ),
                rows=ROWS,
            )
        )

    def status(self) -> str:
        if self.target is None:
            return "SSH is off. Coding tools use the local workspace."
        level = self.policy.level if self.policy is not None else "unavailable"
        transport = self._transports.get(self.target)
        state = transport.status if transport is not None else "not connected"
        return (
            f"SSH target: {json.dumps(self.target.host)} {json.dumps(self.target.path, ensure_ascii=False)}. "
            f"{state}; remote tools require permission full (current: {level})."
        )

    def backend(self, profile: str = "coding") -> RemoteTools:
        if self.target is None or self.policy is None:
            raise RuntimeError("SSH backend is not active")
        transport = self._transports.get(self.target)
        if transport is None:
            transport = self._transports[self.target] = Transport(self.target)
        # One object per child, never shared: SSH2 keeps each child's replacement extensions its own.
        return RemoteTools(self.target, self.policy, profile, transport)

    def parent_backend(self) -> RemoteTools:
        """Return the session's own backend, kept across requests; a child's is built fresh by :meth:`backend`."""
        cached = self._parent_backend
        transport = self._transports.get(self.target) if self.target is not None else None
        if cached is None or cached.target != self.target or cached.transport is not transport:
            cached = self._parent_backend = self.backend()
        return cached

    def child_extensions(self, child: ChildSession) -> tuple[AgentExtension, ...]:
        if self.target is None:
            return ()
        if child.kind != "subagent" or child.profile not in {"explore", "coding", "reasoning"}:
            raise ValueError("SSH child extensions require a known subagent profile")
        extensions: tuple[AgentExtension, ...] = (self.backend(child.profile), NoLocalInstructions())
        # A coding child without an inherited shell has a default FileTools, too; never leave that local backend.
        return (*extensions, NoLocalFiles()) if child.profile == "coding" else extensions

    async def on_state(self, context: AgentRunContext) -> None:
        if self.target is None:
            return
        backend = self.parent_backend()
        for name in tuple(context.tools):
            try:
                reject_local_harness(context, name)
            except PermissionError:
                del context.tools[name]
        for name in ALL:
            if name in context.tools:
                context.tools[name] = backend.tool(name)
        for name in ("glob", "grep"):
            if name not in context.tools:
                context.register_tool(backend.tool(name))
        context.add_message(SystemMessage(content=backend.instructions()))

    async def on_tool_call(self, context: AgentRunContext, call: ToolCall, call_next: ToolCallNext) -> ToolResult:
        if self.target is not None:
            reject_local_harness(context, call.name)
            if call.name in ALL:
                backend = self.parent_backend()
                if backend.policy.level != "full":
                    return await backend.invoke(call.name, call.arguments)
                return await backend.tool(call.name).handler(**call.arguments)
        return await call_next()
