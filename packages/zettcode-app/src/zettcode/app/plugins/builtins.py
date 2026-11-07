"""The rows ZettCode ships with, written as an ordinary plugin.

Keeping the default header and status here — rather than inside
:class:`~zettcode.app.ui.app.ZettCodeApp` — is what leaves the shell with one
generic renderer: it asks the merged plugin bundle for each row side and paints
whatever comes back. The builtin registers its segments first, so a plugin that
overrides one of the same builders replaces it in place instead of adding a
second segment beside it.
"""

from __future__ import annotations

from zettcode.app.ui import labels
from zettcode.engine.plugins.context import PluginContext
from zettcode.plugin_api.plugin import TuiPlugin
from zettcode.plugin_api.state import ShellContext, TurnBuilder
from zettcode.presenters.pulse import activity_glyph
from zettcode.presenters.text import (
    cache_text,
    calls_text,
    elapsed_text,
    speed_text,
    tokens_text,
    tools_text,
)
from zettcode.statusline import TURN_PARTS, Row, context_share, usage_parts
from zettcode.tui import STATUS, bundled_themes

from .groups import require_tui


class ShellRows(TuiPlugin):
    """The header and status rows a reader expects out of the box."""

    name = "shell"

    def render_header_left(self, context: ShellContext) -> Row:
        """Label the app, the session (its title and the name others reach it by), and the workspace."""
        return labels.header_left(context.session.workspace, context.session.name, context.session.handle)

    def render_header_right(self, context: ShellContext) -> Row:
        """Show the model and the reasoning effort the next request will use."""
        return labels.header_right(context.model.name, context.model.effort)

    def render_status_left(self, context: ShellContext) -> Row:
        """Show the activity glyph, status word, mode, and token use; the session is in the header."""
        activity = context.activity
        counters = usage_parts(activity.usage)
        model = context.model.config
        return labels.status_left(
            activity.label,
            icon=activity_glyph(activity.frame) if activity.busy else STATUS,
            permission=activity.permission,
            self_compact=activity.self_compact,
            # With no model configured there is no window to measure the context against, and the row leaves the
            # share out rather than dividing by one it does not have.
            ctx=context_share(activity.usage, model.context_window) if model is not None else "",
            **counters,
        )

    def render_status_right(self, context: ShellContext) -> Row:
        """List the keys worth remembering."""
        return labels.status_right()


class TurnLine(TuiPlugin):
    """The items of the line a request ends on: how long it took, when, and what it spent.

    Each is a segment of its own, so a plugin can add one beside them or replace one by name, and each is a switch
    in ``/statusline``. Written as an ordinary plugin, like the header and status rows above.
    """

    name = "turn-line"

    def activate(self, ctx: PluginContext) -> None:
        """Register the items in the order they stand."""
        tui = require_tui(ctx)
        sentences = dict(TURN_PARTS)
        builders: dict[str, TurnBuilder] = {
            "turn-time": lambda turn: f"{turn.label} for {elapsed_text(turn.seconds)}",
            "turn-clock": lambda turn: turn.clock,
            "turn-tokens": lambda turn: tokens_text(turn.usage),
            "turn-cache": lambda turn: cache_text(turn.usage),
            "turn-calls": lambda turn: calls_text(turn.usage),
            "turn-speed": lambda turn: speed_text(turn.usage),
            "turn-tools": lambda turn: tools_text(turn.tools, turn.failed_tools),
        }
        for name, builder in builders.items():
            tui.register_turn_segment(name, sentences[name], builder)


class BuiltinThemes(TuiPlugin):
    """The palettes that ship with the program, offered the way any plugin offers one.

    They are TOML files beside the theme loader, so adding a built-in palette is adding a file and a name to
    ``BUNDLED``; nothing here knows what a palette looks like. They are registered first, so they are listed first
    in the ``/theme`` menu, and a plugin cannot register a name they hold.
    """

    name = "themes"

    def activate(self, ctx: PluginContext) -> None:
        """Offer each palette file by name. Nothing is read until one is asked for."""
        if ctx.tui is None:
            return  # loaded by a process with no screen (the server): there is nothing to offer a palette to
        tui = require_tui(ctx)
        for source in bundled_themes():
            tui.register_theme(source.name, source.load, description=source.description)


#: Plugins loaded from the repository itself, never from a distribution. They are instances because a ``TuiPlugin``
#: needs nothing to build one; the agent-side ones, which build on state the runtime hands over, are the classes in
#: :data:`~zettcode.sdk.builtins.AGENT_PLUGINS`, instantiated once per load by the loader.
BUILTIN_PLUGINS: tuple[TuiPlugin, ...] = (
    ShellRows(),
    TurnLine(),
)
