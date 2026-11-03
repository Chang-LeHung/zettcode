"""The just-in-time harness, kept behind a switch the reader can flip between two requests.

The framework's :class:`~zett_agent.jit_harness.JITHarnessExtension` lets the model write small Python tools of its
own and run them. That is opt-in by nature, and it is not behind the shell's permission level by itself: the plugin
puts a child process (and, below `full`, a sandbox) between that code and this window. So it is registered always and
does nothing until switched on, which is what lets the ``/plugins`` switch take effect on the next start without rebuilding
the client.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import TYPE_CHECKING

from zett_agent.agent import AgentRunContext
from zett_agent.events import AgentEvent, AgentEventType
from zett_agent.extensions.base import ModelRequestNext, ToolCallNext
from zett_agent.jit_harness import JITHarnessExtension
from zett_agent.messages import ToolCall, ToolMessage
from zett_agent.model import ModelEvent, ModelRequest
from zett_agent.tools.base import ToolResult

from .harness_switch import HarnessSwitch
from .mcp_notice import HARNESS_NOTICE_EVENT_NAME, notice_payload

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zett_agent.jit_harness import JITToolHost

__all__ = ["SwitchedHarness"]


class SwitchedHarness(JITHarnessExtension):
    """The framework's harness, inert while its switch is off.

    Every hook that changes a request first asks the switch. A hook that only releases what a request held is left
    alone, so a request that began with the harness on still lets go of it cleanly. The switch is read once per
    request, in ``on_tool``, because ``/harness`` waits for an idle shell: no request sees it change halfway.
    """

    def __init__(
        self,
        root: str | Path,
        switch: HarnessSwitch,
        *,
        host_factory: Callable[[], JITToolHost] | None = None,
        boundary: Callable[[], str] | None = None,
        unbounded: Callable[[], bool] | None = None,
        legacy_root: str | Path | None = None,
    ) -> None:
        """Keep each session's repository under ``root``, and follow ``switch``.

        Args:
            root: Directory that holds one subdirectory per session.
            switch: Whether the harness is on for a request.
            host_factory: Where a session's repository code runs, called once per session; ``None`` keeps the
                framework's default, which imports it here. The plugin passes one that puts a child process between
                the model's code and this window, inside a sandbox unless the reader gave the model everything.
            boundary: What the host was built for — the shell level, in the plugin's words — read once per request.
                A session's host is made once, so a level that changed since it was built (``/permission full``
                while code was already running under a sandbox) would otherwise leave the old answer in force.
                When it differs, the session is forgotten, which closes its child and builds the next host for the
                level now in force.
            unbounded: Whether the level in force promises a boundary this machine does not have. The code the model
                wrote then runs with the reader's own access, which they are told once per session.
            legacy_root: The root from before the workspace level, whose session directory is moved under ``root``
                the first time that session asks for it.
        """
        super().__init__(root, host_factory=host_factory)
        self._root = Path(root)
        self._legacy_root = Path(legacy_root) if legacy_root is not None else None
        self._switch = switch
        self._boundary = boundary
        self._unbounded = unbounded
        #: Sessions already told that their repository code has no boundary on this machine.
        self._said_unbounded: set[str] = set()
        #: The boundary each session's host was built for, so a change of level is noticed.
        self._built: dict[str, str] = {}
        #: Sessions whose child must be closed once the request in flight lets go of them.
        self._pending: set[str] = set()
        #: Sessions whose current request has the harness, set by ``on_tool`` and cleared when it is released.
        self._engaged: set[str] = set()

    def engaged(self, context: AgentRunContext) -> bool:
        """Return whether this request was given the harness."""
        return context.session_id in self._engaged

    async def on_tool(self, context: AgentRunContext) -> None:
        """Mount the harness's tools, when it is on — in a host built for the level in force now."""
        if self._legacy_root is not None:
            from zettcode.engine.harness_paths import move_session

            move_session(self._legacy_root, self._root, context.session_id)
        if not self._switch.on:
            return
        self._follow_boundary(context.session_id)
        self._engaged.add(context.session_id)
        await self._say_unbounded(context)
        await super().on_tool(context)

    async def _say_unbounded(self, context: AgentRunContext) -> None:
        """Tell the reader, once per session, that this machine cannot bound the code the model writes.

        A machine with no sandbox passes ``None`` to the host, which runs the child with the reader's own access. The
        harness says so because the model's own tools are not a shell command and none of the shell's fallbacks apply
        to them. A line of news must never be what stops a request, so a failure to publish it is dropped.
        """
        if self._unbounded is None or not self._unbounded() or context.session_id in self._said_unbounded:
            return
        try:
            await context.emit(
                AgentEvent(
                    type=AgentEventType.CUSTOM,
                    session_id=context.session_id,
                    name=HARNESS_NOTICE_EVENT_NAME,
                    payload=notice_payload(
                        "this machine has no sandbox, so the tools the model writes run with your own access; "
                        "`/plugins` turns the harness plugin off",
                        "warn",
                    ),
                )
            )
        except Exception:  # noqa: BLE001 - news is never what stops a request
            return
        self._said_unbounded.add(context.session_id)

    def _follow_boundary(self, session_id: str) -> None:
        """Forget a session whose host was built for a boundary that is no longer in force."""
        if self._boundary is None:
            return
        now = self._boundary()
        built = self._built.get(session_id)
        if built is None:
            self._built[session_id] = now
            return
        if built == now:
            return
        # Its child was started without (or with) a boundary the reader has since changed: close it, and let the next
        # request build the host the boundary asks for. A fail-open sandbox is the case that matters. The new value is
        # recorded only once the old child is really gone, so a forget that had to wait is tried again next time.
        if self._forget(session_id):
            self._built[session_id] = now
        else:
            self._pending.add(session_id)

    def _forget(self, session_id: str) -> bool:
        """Close a session's child now, or say that the request in flight still holds it."""
        try:
            self.forget_session(session_id)
        except KeyError:
            # The framework dropped it already (an idle session past its cap): nothing is left to close, and nothing
            # that is keyed by it is worth keeping either.
            self._drop(session_id)
            return True
        except RuntimeError:
            return False
        self._drop(session_id)
        return True

    def _drop(self, session_id: str) -> None:
        """Forget what this window remembered about a session the framework no longer holds."""
        self._built.pop(session_id, None)
        self._said_unbounded.discard(session_id)

    async def on_state(self, context: AgentRunContext) -> None:
        """Adopt late tool registrations, for a request that has the harness."""
        if self.engaged(context):
            await super().on_state(context)

    async def on_tool_call(self, context: AgentRunContext, call: ToolCall, call_next: ToolCallNext) -> ToolResult:
        """Run a call through the harness when it is engaged, and straight through when not."""
        if not self.engaged(context):
            return await call_next()
        return await super().on_tool_call(context, call, call_next)

    async def before_tool(self, context: AgentRunContext, call: ToolCall) -> None:
        """Announce a harness tool call, when engaged."""
        if self.engaged(context):
            await super().before_tool(context, call)

    async def after_tool(
        self, context: AgentRunContext, call: ToolCall, result: ToolMessage, error: Exception | None
    ) -> None:
        """Report a harness tool call's outcome, when engaged."""
        if self.engaged(context):
            await super().after_tool(context, call, result, error)

    async def on_model_request(
        self, context: AgentRunContext, request: ModelRequest, call_next: ModelRequestNext
    ) -> AsyncIterator[ModelEvent]:
        """Add the harness's guidance to the request, when engaged; leave it untouched when not."""
        if not self.engaged(context):
            async for event in call_next(request):
                yield event
            return
        async for event in super().on_model_request(context, request, call_next):
            yield event

    def _release(self, context: AgentRunContext) -> None:
        """Let go of what the request held, and forget that it had the harness."""
        self._engaged.discard(context.session_id)
        # Detach first: the framework refuses to forget a session an active request still holds, and the release is
        # what makes it idle. Only then can the child built for the old boundary be closed.
        super()._release(context)
        if context.session_id in self._pending:
            self._pending.discard(context.session_id)
            if self._forget(context.session_id) and self._boundary is not None:
                self._built[context.session_id] = self._boundary()
