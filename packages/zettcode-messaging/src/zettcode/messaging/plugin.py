"""The plugin that hands the agent the tools for talking to the other sessions open on this machine."""

from __future__ import annotations

from typing import TYPE_CHECKING

from zettcode.engine.delivery import DELIVERY, Delivery
from zettcode.engine.inbox import Inbox as InboxContract
from zettcode.engine.plugins.context import PluginContext
from zettcode.engine.plugins.plugin import Plugin

from .inbox import INBOX, Inbox
from .messenger import SESSION_LINK, Messenger

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zett_agent.extensions.base import AgentExtension

    from zettcode.engine.plugins.state import AgentBuild


class Messaging(Plugin[PluginContext]):
    """The tools that talk to the other sessions open on this machine."""

    name = "messaging"
    description = "The session messaging tools"

    #: The line this plugin built itself, when the front end did not hand one over; this plugin closes it.
    _owned: Messenger | None = None

    def activate(self, ctx: PluginContext) -> None:
        """Provide the inbox, and register the tools when this session has a line to the others.

        The inbox is provided whether or not there is a line: an event from a trigger or a program reaches the agent
        the same way, and a process that never joins the broker still has one. A queue a front end supplied under the
        same name is kept instead, and one that is not an ``Inbox`` is refused rather than silently offering the wrong
        object to every event.

        The line itself is the front end's to hand over by name (``ZettCodeEngine.preview(shared=...)``), and this
        plugin builds one from the configuration when it does not, so a plain SDK client talks to the other sessions
        without wiring anything. A configuration that switches sessions off builds none and registers no tool.
        """
        delivery = ctx.find(DELIVERY, object)
        if isinstance(delivery, Delivery):
            queued = ctx.find(INBOX, object)
            if queued is None:
                ctx.inject(INBOX, Inbox(delivery))
            elif not isinstance(queued, InboxContract):
                raise TypeError(f"The {INBOX!r} service is not an Inbox")

        messenger = ctx.find(SESSION_LINK, Messenger)
        owned = messenger is None
        if messenger is None:
            messenger = Messenger.create(ctx.config)
            if messenger is None:
                return
        link = messenger

        def build(_: AgentBuild) -> AgentExtension:
            from .extension import SessionMessagingExtension

            return SessionMessagingExtension(link)

        # The factory is registered before the name is taken: an injection that fails leaves a plugin the loader
        # drops, and nothing has started the line yet, so there is nothing to leak.
        ctx.agent.register_extension_factory("SessionMessagingExtension", build)
        if owned:
            ctx.inject(SESSION_LINK, link)
            self._owned = link

    async def aclose(self) -> None:
        """Leave the broker, when this plugin was the one that joined it."""
        messenger, self._owned = self._owned, None
        if messenger is not None:
            await messenger.close()
