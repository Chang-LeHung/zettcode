"""The page-facing service contracts, in an engine leaf so plugin-api can re-export them.

The engine owns the names and shapes because the providers are engine objects; the plugin contract re-exports them.
A provider must subclass the ABC: ``lookup`` checks ``isinstance``, not the method names.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zettcode.engine.extensions.context import ContextReport
    from zettcode.engine.storage.ledger import Ledger
    from zettcode.engine.storage.metadata import SessionInfo

SESSION_STORE = "session-store"
USAGE_LEDGER = "usage-ledger"
CONTEXT_REPORT = "context-report"


class SessionStoreService(ABC):
    """The stored sessions of the workspace, as another plugin may list them."""

    NAME: ClassVar[str] = SESSION_STORE

    @abstractmethod
    async def list_sessions(self, *, limit: int = 100, offset: int = 0) -> list[SessionInfo]:
        """Return the workspace's sessions, newest first."""


class UsageLedgerService(ABC):
    """The workspace's usage ledger, read from the stored conversations."""

    NAME: ClassVar[str] = USAGE_LEDGER

    @abstractmethod
    async def ledger(self) -> Ledger:
        """Return the engine's ledger; a page translates it at its own edge."""


class ContextReportService(ABC):
    """The last assembled request of one session."""

    NAME: ClassVar[str] = CONTEXT_REPORT

    @abstractmethod
    async def report(self, session_id: str) -> ContextReport | None:
        """Return the report, or ``None`` when nothing has been assembled."""


__all__ = [
    "CONTEXT_REPORT",
    "SESSION_STORE",
    "USAGE_LEDGER",
    "ContextReportService",
    "SessionStoreService",
    "UsageLedgerService",
]
