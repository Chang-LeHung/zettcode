"""Messages between sessions: sending one with ``@``, receiving one as a turn.

Another ZettCode session reaches this one through the broker (:mod:`zettcode.broker`), and this
one reaches it. The shell's part is small, because a received message is meant to behave like one the
reader typed:

* **Idle** — it starts a turn at once, drawn as a message from that session and not as the reader's
  own, and everything after is an ordinary turn: the wait row, the answer, the summary of what
  changed, the title, the stored session.
* **Busy** — it waits, and starts when the request in flight ends, after what the reader queued. It
  never steers the request: it came from somebody else, and "change what you are doing" is the
  reader's to say.
* **Sending** — a draft that *begins* with ``@name`` of an active session is a message to it, not a
  request to the model: it is sent, whatever this session is doing, and drawn as sent. A session named
  later in the draft is only a reference the model is told about.

The session also tells the broker what it is — its id, title, and whether it is busy — whenever one
of them changes, so the others see a current list. None of this can fail the shell: with no broker the
shell is exactly what it was.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import TYPE_CHECKING

from zettcode.broker.client import Receipt, SendError
from zettcode.broker.protocol import MAX_TEXT, VIA_USER
from zettcode.engine.dialogue.mentions import MENTION
from zettcode.engine.relay import Relayed

from ..agent.agent.prompt import PromptPart, carries_image, plain_text
from .shell import ShellState

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zettcode.broker.client import RosterEntry
    from zettcode.engine.messenger import Messenger

#: Messages from other sessions that may wait for a request to end. A session that is flooded refuses
#: the rest, and the sender is told why, instead of this shell holding an unbounded list.
MAX_INBOX = 16

#: Characters that may separate ``@name`` from the message it addresses: ``@bob: hi`` and ``@bob, hi``.
_SEPARATORS = " \t\r\n,:;"

#: Characters of a waiting message that the notice repeats, so the reader can tell which one it is.
_PREVIEW = 60


class MessagingMixin(ShellState):
    """Hold the line to the other sessions and turn what arrives into turns."""

    #: The line to the broker, or ``None`` when sessions are switched off.
    messenger: Messenger | None
    #: Messages from other sessions waiting for the request in flight to end, oldest first.
    _inbox: list[Relayed]
    #: Sends in flight, held so they are not collected and can be cancelled on exit.
    _sends: set[asyncio.Task[None]]
    #: Whether the connection has been started; before that there is no loop to tell it anything on.
    _messaging_live: bool
    #: The session id the broker was last told about, to notice a switch.
    _messaging_session: str | None
    #: The connection's start, which returns at once but is still a task to be awaited on the way out.
    _messaging_start: asyncio.Future[None] | None
    #: Whether the reader has been told the broker is out of reach, so that being back is worth saying.
    _messaging_trouble: bool

    # -- the life of the connection ---------------------------------------------------------------
    def _start_messaging(self) -> None:
        """Take over the messenger's callbacks and begin connecting. Returns at once."""
        messenger = self.messenger
        if messenger is None:
            return
        messenger.receiver = self._relay_received
        messenger.on_change = self._peers_changed
        messenger.on_conflict = self._messaging_conflict
        messenger.on_problem = self._messaging_problem
        self._messaging_live = True
        self._sync_messaging()
        self._messaging_start = asyncio.ensure_future(messenger.start())

    async def _stop_messaging(self) -> None:
        """Leave the broker and end what is still being sent. Nothing here may delay leaving."""
        messenger = self.messenger
        self._messaging_live = False
        sends = tuple(self._sends)
        for send in sends:
            send.cancel()
        if sends:
            await asyncio.gather(*sends, return_exceptions=True)
        start = self._messaging_start
        if start is not None:
            await asyncio.gather(start, return_exceptions=True)
        if messenger is not None:
            await messenger.close()

    def _sync_messaging(self) -> None:
        """Tell the broker what this session is now: its id, its title, whether it is busy.

        Cheap when nothing changed, so it is called from every place something might have. Before the
        connection is started it does nothing, because the first call after starting says it all.
        """
        messenger = self.messenger
        if messenger is None or not self._messaging_live:
            return
        session = self.agent.session_id
        if self.agent.session_locked:
            # Not this session's to answer for: a message sent to it would be a turn, which is a write.
            messenger.retire()
            self._messaging_session = session
            return
        if self._messaging_session not in (None, session) and self._inbox:
            count = len(self._inbox)
            self.transcript.notice(
                f"{count} message{'s' if count != 1 else ''} from other sessions "
                f"{'were' if count != 1 else 'was'} waiting and will arrive in this session"
            )
        self._messaging_session = session
        messenger.describe(session, self._session_title, busy=self._busy)

    def _peers_changed(self) -> None:
        """Repaint: the completion menu and the styling of an ``@name`` read the current list."""
        self.app.invalidate()

    def _messaging_conflict(self, message: str | None) -> None:
        """Say once that this session cannot be reached, and why."""
        if message:
            self.transcript.notice(f"messages: {message}")
            self.app.invalidate()

    def _messaging_problem(self, message: str | None) -> None:
        """Say that the broker cannot be reached, once it has been a while, and again when it can."""
        if message:
            self._messaging_trouble = True
            self.transcript.notice(f"messages: {message}; trying again")
        elif self._messaging_trouble:
            self._messaging_trouble = False
            self.transcript.notice("messages: connected to the session broker again")
        self.app.invalidate()

    # -- receiving --------------------------------------------------------------------------------
    def _relay_received(self, relayed: Relayed) -> Receipt:
        """Take a message another session sent: start a turn on it, or hold it until this one is free.

        Called by the connection, on the loop, with the sender waiting for the answer; what it returns
        is what the sender's agent is told. It must not block.
        """
        if not self._messaging_live:
            return Receipt(False, "this session is closing")
        if self.agent.session_locked:
            return Receipt(False, "this session is open in another ZettCode process, so it is read-only here")
        if not self._busy:
            self._start_relayed(relayed)
            return Receipt(True, disposition="started")
        if len(self._inbox) >= MAX_INBOX:
            return Receipt(
                False, f"this session already has {len(self._inbox)} messages waiting; try again when it is less busy"
            )
        self._inbox.append(relayed)
        preview = relayed.text.replace("\n", " ")
        if len(preview) > _PREVIEW:
            preview = preview[: _PREVIEW - 1] + "\u2026"
        self.transcript.notice(f"message from {relayed.sender} waits for this request to end: {preview}")
        self.app.invalidate()
        return Receipt(True, disposition="queued")

    def _start_relayed(self, relayed: Relayed) -> None:
        """Run one received message as a turn of its own."""
        # Busy before the task has run, exactly as for a follow-up: between here and its first step a
        # second message, or a keystroke, must not be able to start a turn beside this one.
        self._set_busy(True)
        self._task = asyncio.create_task(self._run_prompt(relayed.text, (relayed.text,), None, relayed=relayed))

    def _start_next_relayed(self) -> bool:
        """Start the oldest waiting message, if there is one and nothing is running."""
        if self._busy or not self._inbox:
            return False
        self._start_relayed(self._inbox.pop(0))
        return True

    # -- sending ----------------------------------------------------------------------------------
    def _session_message(self, parts: Sequence[PromptPart]) -> tuple[str, str] | None:
        """Return ``(name, text)`` when a draft is addressed to an active session, else ``None``.

        A draft is addressed when its first word is ``@name`` and ``name`` is the handle of a session
        that is active now. Anything else — a name nobody has, a name in the middle, a file path — is an
        ordinary draft for the model.
        """
        messenger = self.messenger
        if messenger is None:
            return None
        text = plain_text(parts).lstrip()
        match = MENTION.match(text)
        if match is None:
            return None
        peer = messenger.find(match.group(1))
        if peer is None:
            return None
        return peer.handle, text[match.end() :].lstrip(_SEPARATORS).rstrip()

    def _send_session_message(self, parts: Sequence[PromptPart]) -> bool | None:
        """Send a draft addressed to a session, or say why it cannot be.

        Returns:
            ``None`` when the draft is not addressed to a session and the caller should treat it as any
            other; otherwise what :meth:`submit` returns — ``True`` when the draft was taken and the
            composer should clear, ``False`` when it was not and the draft stays to be fixed.
        """
        found = self._session_message(parts)
        if found is None:
            return None
        name, text = found
        if carries_image(parts):
            self.flash(f"a message to @{name} is text only", level="error")
            return False
        if not text:
            self.flash(f"write the message after @{name}", level="error")
            return False
        if len(text) > MAX_TEXT:
            self.flash(f"a message is limited to {MAX_TEXT} characters; this is {len(text)}", level="error")
            return False
        peer = self.messenger.find(name) if self.messenger is not None else None
        if peer is None:  # went away between the two lookups: nothing was addressed
            return None
        task = asyncio.create_task(self._deliver(peer, text))
        self._sends.add(task)
        task.add_done_callback(self._sends.discard)
        return True

    async def _deliver(self, peer: RosterEntry, text: str) -> None:
        """Send one message and put the outcome in the conversation: the message, or why it was not taken."""
        messenger = self.messenger
        if messenger is None:
            return
        try:
            delivered = await messenger.send(peer.session_id, text, via=VIA_USER)
        except SendError as error:
            self.transcript.error(f"not sent to @{peer.handle}: {error}")
        except Exception as error:  # noqa: BLE001 - a bug here must not be silent, and must not end the shell
            self.transcript.error(f"not sent to @{peer.handle}: {type(error).__name__}")
        else:
            note = "queued" if delivered.disposition == "queued" else "delivered"
            self.transcript.sent_message(delivered.to.handle, text, note)
        self.app.invalidate()
