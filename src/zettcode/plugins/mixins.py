"""The hook groups a plugin can implement, split by the stage they observe.

Mirrors ``zett-agent``'s extension mixins one for one, so an author who knows
the extension docs already knows where a hook belongs. :class:`PluginAgentMixin`
bundles the agent flow; :class:`PluginUiMixin` is this application's row
group. Every hook defaults to doing nothing.
"""

from __future__ import annotations

from contextlib import aclosing
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:  # pragma: no cover - annotations only, so the imports stay lazy
    from collections.abc import AsyncGenerator, AsyncIterator

    from zett_agent.agent import AgentRunConfig, AgentRunContext
    from zett_agent.extensions.base import ModelRequestNext, ToolCallNext
    from zett_agent.extensions.events import ExtensionEvent
    from zett_agent.extensions.external import ExternalEvent
    from zett_agent.messages import AssistantMessage, ToolCall, ToolMessage
    from zett_agent.model import ModelEvent, ModelRequest, ModelResponse
    from zett_agent.tools.base import ToolResult

    from .state import ShellContext, UiBuilder, UiBuilderResult, UiRegion, UiSide

#: ``(method, region, side)`` for every slot the UI mixin exposes, in paint
#: order. The method name minus its prefix is the segment name a plugin's
#: override registers under.
UI_SLOTS: tuple[tuple[str, UiRegion, UiSide], ...] = (
    ("render_header_left", "header", "left"),
    ("render_header_right", "header", "right"),
    ("render_status_left", "status", "left"),
    ("render_status_right", "status", "right"),
)


class PluginSetupMixin:
    """Setup hooks: request-scoped tools and conversation context.

    Runs before any input is converted, so a plugin can register tools or
    restore state that later hooks already see.
    """

    async def on_tool(self, context: AgentRunContext) -> None:
        """Register local or provider-hosted tools before context restoration."""

    async def on_state(self, context: AgentRunContext) -> None:
        """Restore history and initialize state before any input conversion."""

    async def on_message(self, context: AgentRunContext) -> None:
        """Transform the pending user message after state restoration."""


class PluginRunMixin:
    """Hooks around one complete request and its terminal outcome."""

    async def before_run(self, context: AgentRunContext) -> None:
        """Run after the transformed user input is appended and published."""

    async def after_run(self, context: AgentRunContext, result: AssistantMessage) -> None:
        """Run after a successful final answer is appended."""

    async def on_success(self, context: AgentRunContext, result: AssistantMessage) -> None:
        """Run once after a request completes successfully."""

    async def on_error(self, context: AgentRunContext, error: Exception) -> None:
        """Run before an agent error is propagated to the caller."""


class PluginTurnMixin:
    """Hooks around one model/tool turn inside a request."""

    async def before_turn(self, context: AgentRunContext) -> None:
        """Run before this turn's model call, after request assembly."""

    async def after_turn(self, context: AgentRunContext, result: AssistantMessage) -> None:
        """Run once the turn's assistant message and tool results are settled."""


class PluginModelMixin:
    """Hooks immediately before and after each primary model invocation."""

    async def before_model(self, context: AgentRunContext, request: ModelRequest) -> None:
        """Inspect the request before preprocessing a primary model call."""

    async def after_model(self, context: AgentRunContext, response: ModelResponse) -> None:
        """Run after the complete assistant message is appended."""


class PluginToolMixin:
    """Hooks immediately before and after each requested tool invocation."""

    async def before_tool(self, context: AgentRunContext, call: ToolCall) -> None:
        """Run before one requested tool is invoked."""

    async def after_tool(
        self,
        context: AgentRunContext,
        call: ToolCall,
        result: ToolMessage,
        error: Exception | None,
    ) -> None:
        """Inspect or modify a tool result before it is appended."""


class PluginMaintenanceMixin:
    """Hooks for work a caller asks for outside a model turn."""

    async def on_compact(self, context: AgentRunContext) -> None:
        """Do the plugin's part of a compaction a caller asked for."""


class PluginEventMixin:
    """Hooks for internal notifications and external input."""

    def accept(self, config: AgentRunConfig | None, event: ExternalEvent) -> bool:
        """Handle one external event and report whether it was accepted."""
        return False

    async def on_event(self, context: AgentRunContext, event: ExtensionEvent) -> None:
        """Process a published notification; inspect its concrete type with ``match``."""


class PluginMiddlewareMixin:
    """Middleware that wraps the provider stream and the tool handlers."""

    async def on_model_request(
        self,
        context: AgentRunContext,
        request: ModelRequest,
        call_next: ModelRequestNext,
    ) -> AsyncIterator[ModelEvent]:
        """Wrap one provider request and its complete streamed response."""
        # ``call_next`` widens to AsyncIterator, which aclosing cannot type-check;
        # the provider stream is the async generator behind it.
        stream = cast("AsyncGenerator[ModelEvent]", call_next(request))
        async with aclosing(stream) as events:
            async for event in events:
                yield event

    async def on_tool_call(
        self,
        context: AgentRunContext,
        call: ToolCall,
        call_next: ToolCallNext,
    ) -> ToolResult:
        """Wrap one registered local tool handler and return its result."""
        return await call_next()


class PluginAgentMixin(
    PluginSetupMixin,
    PluginRunMixin,
    PluginTurnMixin,
    PluginModelMixin,
    PluginToolMixin,
    PluginMaintenanceMixin,
    PluginEventMixin,
    PluginMiddlewareMixin,
):
    """The agent-flow group: every hook the model/tool lifecycle offers.

    It bundles the finer groups below it — setup, run, turn, model, tool,
    maintenance, events, and middleware — so ``PluginAgentMixin`` names the
    whole surface in one base and an import can choose the granularity it
    wants: the umbrella for "this plugin drives the agent", one group for "this
    plugin only wants the tool stage".
    """


class PluginUiMixin:
    """The four shell slots a plugin can fill.

    Each method is one named slot: the header's and the status line's left and
    right sides. Override one and it is registered under that slot's name, so
    overriding the method a builtin already implements replaces that segment
    rather than adding a second one. A plugin that needs another segment beside
    the builtin's, or decides what to register from the configuration, uses
    ``PluginContainer.register_*`` in :meth:`Plugin.activate`.

    The names are deliberately specific, so a plugin's own ``status`` or
    ``header`` helper cannot be mistaken for a contribution. A builder returns
    the segment, or ``(segment, True)`` to take the side over and drop what the
    segments before it painted.
    """

    def render_header_left(self, context: ShellContext) -> UiBuilderResult:
        """Return the header's left segment, or ``(segment, True)`` to take the side over."""
        return None

    def render_header_right(self, context: ShellContext) -> UiBuilderResult:
        """Return the header's right segment, or ``(segment, True)`` to take the side over."""
        return None

    def render_status_left(self, context: ShellContext) -> UiBuilderResult:
        """Return the status line's left segment, or ``(segment, True)`` to take the side over."""
        return None

    def render_status_right(self, context: ShellContext) -> UiBuilderResult:
        """Return the status line's right segment, or ``(segment, True)`` to take the side over."""
        return None

    def ui_slots(self) -> tuple[tuple[UiRegion, UiSide, str, UiBuilder], ...]:
        """Return the slots this plugin overrides, ready to register.

        The segment name is the method's slot name, which is what makes an
        override land on the builtin segment instead of beside it.
        """
        declared: list[tuple[UiRegion, UiSide, str, UiBuilder]] = []
        for name, region, side in UI_SLOTS:
            if getattr(type(self), name) is not getattr(PluginUiMixin, name):
                declared.append((region, side, name.removeprefix("render_"), getattr(self, name)))
        return tuple(declared)
