"""Session switching, restoration, and the background title.

Switching sessions replaces the visible history, restores the store's title,
and asks the agent to name a new session once, off the composer's critical path.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from .shell import ShellState
from .widgets import WELCOME

if TYPE_CHECKING:  # pragma: no cover - annotations only
    pass


class SessionMixin(ShellState):
    """Switch the active session and keep its title current."""

    async def rename_session(self, title: str) -> str:
        """Name the active session and show it in the status line.

        Args:
            title: Name the user typed; the store rejects a blank or over-long
                one, which the command turns into a notice.

        Returns:
            The stored title, so the command can confirm it.
        """
        renamed = await self.agent.rename_session(title)
        self._session_title = renamed
        self.app.invalidate()
        return renamed

    def select_session(self, session_id: str) -> None:
        """Switch to the session picked in the panel and return to the composer."""
        try:
            self.restore_session(session_id)
        except ValueError as error:
            self.transcript.error(str(error))
            self.close_page()
            return
        # Close the panel first: the toast is its own screen, and closing it
        # instead of the panel would leave the picker on top.
        self.close_page()
        self.notify(f"using session {session_id[:8]}", level="success")

    def restore_session(self, session_id: str) -> None:
        """Replace the visible history with the chosen persisted branch."""
        self.agent.restore_session(session_id, self.transcript)
        if not self.transcript.entries:
            self.transcript.welcome(WELCOME)
        self.view.follow_tail = True
        self.view.clear_selection()
        self._remember_session_title()
        self._usage = self.agent.usage
        self._refresh_tasks()
        self.app.request_layout()

    def _remember_session_title(self) -> None:
        """Cache the active session's title, which the status line paints per frame."""
        self._session_title = self.agent.session_title

    def _title_session_later(self, session_id: str) -> None:
        """Ask the agent to name a session once, off the composer's critical path."""
        if self._title_task is not None and not self._title_task.done():
            return
        self._title_task = asyncio.create_task(self._name_session(session_id))

    async def _name_session(self, session_id: str) -> None:
        """Store the title the agent summarizes and show it in the status line."""
        try:
            title = await self.agent.title_session(session_id)
        except Exception:
            return  # naming a session is a nicety; never report its failure
        if title is None:
            return
        if session_id == self.agent.session_id:
            self._session_title = title
            self.app.invalidate()

    async def _stop_title_task(self) -> None:
        """Stop a title request that is still in flight when the app exits."""
        if self._title_task is None or self._title_task.done():
            return
        self._title_task.cancel()
        await asyncio.gather(self._title_task, return_exceptions=True)
