"""The page-facing service contracts, in an engine leaf so plugin-api can re-export them.

The engine owns the names and shapes because the providers are engine objects; the plugin contract re-exports them.
A provider must subclass the ABC: ``lookup`` checks ``isinstance``, not the method names.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from pathlib import Path

    from zettcode.engine.extensions.context import ContextReport
    from zettcode.engine.storage.ledger import Ledger
    from zettcode.engine.storage.metadata import SessionInfo

SESSION_STORE = "session-store"
USAGE_LEDGER = "usage-ledger"
CONTEXT_REPORT = "context-report"
CONTEXT_PAGE = "context-page"


class SessionStoreService(ABC):
    """The stored sessions of the workspace, as another plugin may list them."""

    NAME: ClassVar[str] = SESSION_STORE

    @abstractmethod
    async def list_sessions(self, *, limit: int = 100, offset: int = 0) -> list[SessionInfo]:
        """Return the workspace's sessions, newest first."""

    @abstractmethod
    def session_path(self, session_id: str) -> Path:
        """Return the file one session's conversation is stored in; it may not exist yet.

        Raises:
            ValueError: For an id that would leave the store.
        """


class UsageLedgerService(ABC):
    """The workspace's usage ledger, read from the stored conversations."""

    NAME: ClassVar[str] = USAGE_LEDGER

    @abstractmethod
    async def ledger(self) -> Ledger:
        """Return the engine's ledger; a page translates it at its own edge."""


@dataclass(frozen=True, slots=True)
class ContextPageSnapshot:
    """The model, window and session values the `/context` page draws beside its report."""

    model_name: str
    context_window: int
    compaction_max_tokens: int
    compact_percent: float
    session_path: str


ContextPageWriter = Callable[[float], tuple[str, str | None]]


class ContextPageService(ABC):
    """The `/context` page's shell-owned values, without the page importing CommandHost."""

    NAME: ClassVar[str] = CONTEXT_PAGE

    @abstractmethod
    async def snapshot(self, session_id: str) -> ContextPageSnapshot:
        """Return the model/session values for one session."""

    @abstractmethod
    def bind_writer(self, writer: ContextPageWriter) -> None:
        """Bind the config writer used by :meth:`set_compact_percent`.

        This is a provider hook, called by the runtime/SDK when the agent exists; a page plugin only reads the service.
        """

    @abstractmethod
    def set_compact_percent(self, percent: float) -> tuple[str, str | None]:
        """Write the compaction point and return the model name and any reason it was not saved."""


class ContextReportService(ABC):
    """The last assembled request of one session."""

    NAME: ClassVar[str] = CONTEXT_REPORT

    @abstractmethod
    async def report(self, session_id: str) -> ContextReport | None:
        """Return the report, or ``None`` when nothing has been assembled."""


__all__ = [
    "CONTEXT_PAGE",
    "CONTEXT_REPORT",
    "SESSION_STORE",
    "USAGE_LEDGER",
    "ContextPageService",
    "ContextPageSnapshot",
    "ContextPageWriter",
    "ContextReportService",
    "SessionStoreService",
    "UsageLedgerService",
]
