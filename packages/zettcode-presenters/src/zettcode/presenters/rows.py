"""The header and status rows the program ships, and the line a request ends on.

They are ordinary plugins of the terminal, offered through the ``zettcode.plugin`` entry points like any other part;
the program loads them ahead of a reader's plugins, so a plugin can replace a row by name.
"""

from __future__ import annotations

from zettcode.plugin_api import PluginContext
from zettcode.plugin_api.plugin import TuiPlugin
from zettcode.plugin_api.state import ShellContext, TurnBuilder
from zettcode.presenters import labels
from zettcode.presenters.pulse import activity_glyph
from zettcode.presenters.statusline import TURN_PARTS, Row, context_share, usage_parts
from zettcode.presenters.text import (
    cache_text,
    calls_text,
    elapsed_text,
    speed_text,
    tokens_text,
    tools_text,
)
from zettcode.tui import STATUS


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
        if ctx.tui is None:
            raise RuntimeError("turn-line is a terminal part and needs a screen")
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
            ctx.tui.register_turn_segment(name, sentences[name], builder)
