"""The application-facing coding agent: one class, assembled from the parts that make it up.

The class used to be one 750-line body doing eight unrelated jobs. It is divided the way the
transcript and the shell are, by what each part is responsible for:

==============  ===========================================================================
``base``        :class:`AgentBase` — the runtime, the workspace, the active session id
``settings``    :class:`SettingsMixin` — model, reasoning effort, shell permission
``context``     :class:`ContextMixin` — the request the next turn carries; compaction
``sessions``    :class:`SessionsMixin` — switch, resume, fork, list, and title sessions
``turns``       :class:`TurnsMixin` — build a request, stream its events, steer it
``interaction`` :class:`InteractionMixin` — answer an approval request or a question
``exports``     :class:`ExportsMixin` — write a session out as a page
``commands``    :class:`CommandsMixin` — the agent's commands and what plugins contributed
``prompt``      the parts of a user turn: text, ``@`` references, images (no class)
==============  ===========================================================================

A mixin inherits the ones whose methods it really calls, and :class:`AgentBase` below all of
them, so each is type-checked against what it relies on; nothing is declared twice. This class
is the composition and the lifecycle — building the runtime, and closing it.
"""

from __future__ import annotations

from zettcode.config import ZettCodeConfig

from ..runtime import ZettCodeEngine
from .commands import CommandsMixin
from .context import ContextMixin
from .exports import ExportsMixin
from .interaction import InteractionMixin
from .sessions import SessionsMixin
from .settings import SettingsMixin
from .turns import TurnsMixin


class ZettCodeAgent(
    CommandsMixin,
    InteractionMixin,
    TurnsMixin,
    ExportsMixin,
    SessionsMixin,
    SettingsMixin,
    ContextMixin,
):
    """Expose agent operations without leaking runtime resources to the UI.

    The runtime assembles the vendor client and extensions; this class is the
    application's entry point for turns, session and model selection, progress,
    and responses to approval requests.
    """

    def __init__(self, runtime: ZettCodeEngine) -> None:
        self.runtime = runtime

    @classmethod
    async def create(cls, config: ZettCodeConfig) -> ZettCodeAgent:
        """Build the runtime and wrap it in the application agent."""
        return cls(await ZettCodeEngine.create(config))

    @classmethod
    def preview(cls, config: ZettCodeConfig) -> ZettCodeAgent:
        """Wrap a runtime that still has to start, so a shell can paint first.

        The runtime here holds the session and this application's own
        extensions; the provider SDK and the client are built by the first
        :meth:`runtime.start`, which a turn or a command awaits. Everything the
        shell reads per frame — the model, the effort, the session, the usage —
        is answered from that preview.
        """
        return cls(ZettCodeEngine.preview(config))

    async def aclose(self) -> None:
        """Release the underlying runtime resources."""
        await self.runtime.aclose()
