"""The plugin that hands the agent the tools for talking to the other sessions open on this machine."""

from __future__ import annotations

from typing import TYPE_CHECKING

from zettcode.engine.delivery import DELIVERY, Delivery
from zettcode.engine.plugins.plugin import Plugin
from zettcode.engine.plugins.services import MESSENGER

from .inbox import INBOX, Inbox
from .messenger import Messenger

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zett_agent.extensions.base import AgentExtension

    from zettcode.engine.plugins.context import PluginContext
    from zettcode.engine.plugins.state import AgentBuild


class Messaging(Plugin):
    """The tools that talk to the other sessions open on this machine."""

    name = "messaging"
    description = "The session messaging tools"

    def activate(self, ctx: PluginContext) -> None:
        """Provide the inbox, and register the tools when the runtime gave this session a line to the others.

        The inbox is provided whether or not there is a messenger: an event from a trigger or a program reaches the
        agent the same way, and a process that never joins the broker still has one.
        """
        delivery = ctx.find(DELIVERY, object)
        if isinstance(delivery, Delivery):
            ctx.inject(INBOX, Inbox(delivery))

        messenger = ctx.find(MESSENGER, Messenger)
        if messenger is None:
            return

        def build(_: AgentBuild) -> AgentExtension:
            from .extension import SessionMessagingExtension

            return SessionMessagingExtension(messenger)

        ctx.agent.register_extension_factory("SessionMessagingExtension", build)
