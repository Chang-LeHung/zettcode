"""The just-in-time harness, kept behind a switch the reader can flip between two requests.

The framework's :class:`~zett_agent.jit_harness.JITHarnessExtension` lets the model write small Python tools of its
own and run them. That is opt-in by nature: what the model writes runs in this process, with this user's access, and
is not behind the shell's permission level. So it is registered always and does nothing until switched on, which is
what lets ``/harness on`` take effect on the next request without rebuilding the client.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from zett_agent.agent import AgentRunContext
from zett_agent.extensions.base import ModelRequestNext, ToolCallNext
from zett_agent.jit_harness import JITHarnessExtension
from zett_agent.messages import ToolCall, ToolMessage
from zett_agent.model import ModelEvent, ModelRequest
from zett_agent.tools.base import ToolResult

from .harness_switch import HarnessSwitch

__all__ = ["SwitchedHarness"]


class SwitchedHarness(JITHarnessExtension):
    """The framework's harness, inert while its switch is off.

    Every hook that changes a request first asks the switch. A hook that only releases what a request held is left
    alone, so a request that began with the harness on still lets go of it cleanly. The switch is read once per
    request, in ``on_tool``, because ``/harness`` waits for an idle shell: no request sees it change halfway.
    """

    def __init__(self, root: str | Path, switch: HarnessSwitch) -> None:
        """Keep each session's repository under ``root``, and follow ``switch``."""
        super().__init__(root)
        self._switch = switch
        #: Sessions whose current request has the harness, set by ``on_tool`` and cleared when it is released.
        self._engaged: set[str] = set()

    def engaged(self, context: AgentRunContext) -> bool:
        """Return whether this request was given the harness."""
        return context.session_id in self._engaged

    async def on_tool(self, context: AgentRunContext) -> None:
        """Mount the harness's tools, when it is on."""
        if not self._switch.on:
            return
        self._engaged.add(context.session_id)
        await super().on_tool(context)

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
        super()._release(context)
