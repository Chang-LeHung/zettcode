"""The commands every front end can run: an answer in words, no page and no screen.

The terminal has its own, richer versions — ``/title`` shares a page with the session panel — and they are registered
only where there is a screen. These are what a front end without one (the server, and the editor behind it) lists through
``GET /commands`` and runs through ``POST /commands/{name}``; the terminal's are loaded instead when ``ctx.tui`` is there,
so the two never both answer to one name.

A command that acts on the conversation does it through the front end's host (:class:`PlainCommandHost`); one that is
only words does not need it.
"""

from __future__ import annotations

from zettcode.engine.plugins.commands import PlainCommandContext, TextCommandResult
from zettcode.engine.plugins.context import PluginContext
from zettcode.engine.plugins.plugin import Plugin

__all__ = ["CommandLine"]

#: What a command says when the front end running it has no reach into the session.
_NO_HOST = "This front end cannot do that; run the command in the terminal or through the server."


class CommandLine(Plugin[PluginContext]):
    """``/compact``, ``/title`` and ``/export``, for a front end with no screen.

    Carrying a request on is not here: a turn belongs to the front end that owns the run loop — its approvals, its
    stop button, its events — so a front end without a screen has an endpoint for it (``POST /runs/resume``) and no
    command that would start one behind its back.
    """

    name = "commandline"
    description = "The commands every front end can run"

    def activate(self, ctx: PluginContext) -> None:
        """Register the three; a process with a screen keeps the terminal's own, richer versions instead."""
        if ctx.tui is not None:
            return
        ctx.commands.register(
            "/compact",
            "compact the conversation now, instead of waiting for the window to fill",
            self.compact,
            when_busy="refuse",
        )
        ctx.commands.register(
            "/title",
            "name this session: /title [name]",
            self.title,
            when_busy="now",
        )
        ctx.commands.register(
            "/export",
            "write this session to a standalone HTML file: /export [path]",
            self.export,
            when_busy="refuse",
        )

    async def compact(self, context: PlainCommandContext) -> TextCommandResult:
        """Compact the conversation now."""
        if context.host is None:
            return TextCommandResult(notification=_NO_HOST)
        return TextCommandResult(notification=await context.host.compact())

    async def title(self, context: PlainCommandContext) -> TextCommandResult:
        """Read the session's name, or set it when one is given."""
        if context.host is None:
            return TextCommandResult(notification=_NO_HOST)
        return TextCommandResult(notification=await context.host.title(context.argument.strip() or None))

    async def export(self, context: PlainCommandContext) -> TextCommandResult:
        """Write the session out, and say where."""
        if context.host is None:
            return TextCommandResult(notification=_NO_HOST)
        return TextCommandResult(notification=await context.host.export(context.argument.strip() or None))
