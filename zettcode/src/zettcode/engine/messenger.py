"""This session's line to the others: who is active, a message sent, a message received.

The broker client (:mod:`zettcode.broker.client`) knows the wire; this is the part the rest of the
application holds. The shell tells it what the session is now and gives it a place to hand a received
message to, and the ``send_message`` tool and the ``@`` completion ask it who else is there.

It owns one fact the client cannot know: which message the running turn is answering. An agent that
is answering another agent carries that message's hop count on, which is what stops two sessions
that keep replying to each other; a turn that began with the reader's own words starts at none.

Nothing here blocks or raises into the shell. Without a broker every method answers as if nobody
else were running, and a send says so.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from zettcode.broker.client import BrokerClient, Delivered, Incoming, Receipt, RosterEntry, SessionInfo
from zettcode.broker.protocol import VIA_AGENT
from zettcode.config import ZettCodeConfig

from .relay import Relayed

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from pathlib import Path


class Messenger:
    """The shell's and the agent's one handle on the other sessions."""

    def __init__(self, client: BrokerClient | None = None, *, workspace: str | Path = "") -> None:
        """Wrap a client; one is built for the default broker when none is given.

        Args:
            client: The connection to use. Its callbacks are taken over, so give a client that nothing
                else is listening to.
            workspace: The directory this session works in, which other sessions are shown.
        """
        self.workspace = str(workspace)
        self.client = client if client is not None else BrokerClient()
        self.client.on_message = self._received
        self.client.on_roster = self._roster_changed
        self.client.on_conflict = self._conflicted
        self.client.on_problem = self._troubled
        #: Where a received message goes; the shell sets it. It returns what this session says to the
        #: sender: whether it took the message, and what will become of it.
        self.receiver: Callable[[Relayed], Receipt] | None = None
        #: Called, on the loop, whenever the roster or the connection changes, so a view can repaint.
        self.on_change: Callable[[], None] | None = None
        #: Called with a sentence when another process holds this session's id, and with ``None`` after.
        self.on_conflict: Callable[[str | None], None] | None = None
        #: Called with a sentence when the broker has been out of reach for a while, and with ``None`` when it is back.
        self.on_problem: Callable[[str | None], None] | None = None
        #: The message the running turn answers, if it answers one.
        self.answering: Relayed | None = None
        self._started = False

    @classmethod
    def create(cls, config: ZettCodeConfig) -> Messenger | None:
        """Return the messenger this configuration asks for, or ``None`` when sessions are switched off."""
        if not config.sessions_enabled:
            return None
        return cls(workspace=config.workspace)

    # -- the life of the connection ---------------------------------------------------------------
    @property
    def started(self) -> bool:
        """Return whether :meth:`start` has run, which is when it is safe to tell it about the session."""
        return self._started

    async def start(self) -> None:
        """Begin connecting in the background. Returns at once, whether or not a broker exists."""
        self._started = True
        await self.client.start()

    async def close(self) -> None:
        """Leave the broker. Quick, and safe to call twice."""
        self._started = False
        self.receiver = None
        await self.client.close()

    # -- what this session is ---------------------------------------------------------------------
    def describe(self, session_id: str, title: str | None, *, busy: bool) -> None:
        """Say what this session is now. Cheap when nothing changed, so callers need not check.

        Args:
            session_id: The active session.
            title: Its title, or ``None`` while it has none.
            busy: Whether a request or command is running.
        """
        info = SessionInfo(
            session_id=session_id,
            title=title or "",
            workspace=self.workspace,
            status="working" if busy else "idle",
        )
        current = self.client.session
        if current is not None and (current.session_id, current.title, current.status) == (
            info.session_id,
            info.title,
            info.status,
        ):
            return
        self.client.set_session(info)

    def retire(self) -> None:
        """Say that this process has no session to be reached at: it only shows one that another process has open."""
        if self.client.session is not None:
            self.client.set_session(None)

    # -- the others -------------------------------------------------------------------------------
    @property
    def connected(self) -> bool:
        """Return whether the broker is reachable right now."""
        return self.client.connected

    @property
    def conflict(self) -> str | None:
        """Return why this session is not registered, or ``None``."""
        return self.client.conflict

    @property
    def handle(self) -> str:
        """Return the name the others call this session by, or ``""`` before it is registered."""
        mine = self.client.session
        if mine is None:
            return ""
        return next((entry.handle for entry in self.client.roster if entry.session_id == mine.session_id), "")

    def peers(self) -> tuple[RosterEntry, ...]:
        """Return the other active sessions, from memory: this is called as a draft is typed."""
        return self.client.others()

    def find(self, handle: str) -> RosterEntry | None:
        """Return the other session whose handle is ``handle`` (capitals do not matter), or ``None``."""
        wanted = handle.casefold()
        for entry in self.client.others():
            if entry.handle.casefold() == wanted:
                return entry
        return None

    # -- sending ----------------------------------------------------------------------------------
    async def send(self, to: str, text: str, *, via: str = VIA_AGENT) -> Delivered:
        """Send a message and return once the other session has taken it.

        A message sent by this session's agent while it is answering another one carries that message's
        hop count on; a message the reader sent starts again at none.

        Raises:
            SendError: Nobody was reached, and why.
        """
        hops = self.answering.hops if self.answering is not None and via == VIA_AGENT else 0
        return await self.client.send(to, text, hops=hops, via=via)

    # -- what the client reports ------------------------------------------------------------------
    def _received(self, incoming: Incoming) -> Receipt:
        """Turn the client's message into the shell's and ask the shell to take it."""
        receiver = self.receiver
        if receiver is None:
            return Receipt(False, "this session is not taking messages yet")
        sender = incoming.sender
        return receiver(
            Relayed(
                sender_id=sender.session_id,
                sender=sender.handle,
                text=incoming.text,
                via=incoming.via,
                hops=incoming.hops,
            )
        )

    def _roster_changed(self, roster: tuple[RosterEntry, ...]) -> None:
        if self.on_change is not None:
            self.on_change()

    def _conflicted(self, message: str | None) -> None:
        if self.on_conflict is not None:
            self.on_conflict(message)

    def _troubled(self, message: str | None) -> None:
        if self.on_problem is not None:
            self.on_problem(message)
