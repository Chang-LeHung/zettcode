"""The agent: one class, assembled from the parts that make it up.

The class used to be one 750-line body doing eight unrelated jobs. It is divided by what each part is responsible for:

==============  ===========================================================================
``base``        :class:`AgentBase` — the engine, the workspace, the active session id
``settings``    :class:`SettingsMixin` — model, reasoning effort, shell permission
``context``     :class:`ContextMixin` — the request the next turn carries; compaction
``sessions``    :class:`SessionsMixin` — switch, resume, fork, list, and title sessions
``turns``       :class:`TurnsMixin` — build a request, stream its events, steer it
``interaction`` :class:`InteractionMixin` — answer an approval request or a question
``exports``     :class:`ExportsMixin` — write a session out as a page
``prompt``      the parts of a user turn: text, ``@`` references, images (no class)
==============  ===========================================================================

A mixin inherits the ones whose methods it really calls, and :class:`AgentBase` below all of them, so each is
type-checked against what it relies on; nothing is declared twice. This class is the composition and the
lifecycle — building the engine, and closing it. It knows nothing of the terminal: the terminal's commands and
preferences are a subclass of its own (``zettcode.app.agent.agent.TerminalAgent``).
"""

from __future__ import annotations

from typing import TypeVar

from zettcode.config import ZettCodeConfig
from zettcode.engine.core import ZettCodeEngine

from .context import ContextMixin
from .exports import ExportsMixin
from .interaction import InteractionMixin
from .sessions import SessionsMixin
from .settings import SettingsMixin
from .turns import TurnsMixin

__all__ = ["ZettCodeAgent"]

AgentT = TypeVar("AgentT", bound="ZettCodeAgent")


class ZettCodeAgent(
    InteractionMixin,
    TurnsMixin,
    ExportsMixin,
    SessionsMixin,
    SettingsMixin,
    ContextMixin,
):
    """Expose agent operations without leaking engine resources to the front end.

    The engine assembles the vendor client and extensions; this class is the entry point for turns, session and
    model selection, progress, and responses to approval requests.
    """

    def __init__(self, runtime: ZettCodeEngine) -> None:
        self.runtime = runtime

    @classmethod
    async def create(cls: type[AgentT], config: ZettCodeConfig) -> AgentT:
        """Build the engine and wrap it in the agent."""
        return cls(await ZettCodeEngine.create(config))

    @classmethod
    def preview(cls: type[AgentT], config: ZettCodeConfig) -> AgentT:
        """Wrap an engine that still has to start, so a front end can paint first.

        The engine here holds the session and the extensions this application owns; the provider SDK and the
        client are built by the first :meth:`runtime.start`, which a turn or a command awaits. Everything a front
        end reads per frame — the model, the effort, the session, the usage — is answered from that preview.
        """
        return cls(ZettCodeEngine.preview(config))

    async def aclose(self) -> None:
        """Release the underlying engine resources."""
        await self.runtime.aclose()
