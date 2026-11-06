"""Messages between sessions: receiving one as a turn, and what the broker knows about this one.

Another ZettCode session reaches this one through the broker (:mod:`zettcode.broker`), and this
one reaches it through the model. The shell's receiving part is small, because a message is meant to
behave like one the reader typed:

* **Idle** — it starts a turn at once, drawn as a message from that session and not as the reader's
  own, and everything after is an ordinary turn: the wait row, the answer, the summary of what
  changed, the title, the stored session.
* **Busy** — it follows its ``mode``. A steer message (the default) is handed to the request that is running, so
  it changes course now; one that cannot be steered — a command is running, the steering limit is reached, or the
  sender asked for a follow-up — waits and starts when the request in flight ends, after what the reader queued.
  A message from a reader's one-to-one chat window always waits, because the window is answered by the turn that
  message starts.

The shell sends nothing itself. ``@name`` in a draft is resolved like any other reference
(:mod:`zettcode.mentions`): the model reads which session it means and how to reach it, and calls
``send_message`` itself when the request calls for one.

The session also tells the broker what it is — its id, title, and whether it is busy — whenever one
of them changes, so the others see a current list. None of this can fail the shell: with no broker the
shell is exactly what it was.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from zettcode.broker.client import Receipt
from zettcode.messaging.relay import PREVIEW, Relay
from zettcode.relay import Relayed

from .shell import ShellState

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from ..agent.agent import SessionLink

#: Characters of a waiting message that the notice repeats, so the reader can tell which one it is.
_PREVIEW = PREVIEW


class MessagingMixin(ShellState):
    """Hold the line to the other sessions and show what arrives, leaving the queue and the receipts to the relay."""

    #: The line to the broker, or ``None`` when sessions are switched off.
    messenger: SessionLink | None
    #: What arrives from another session and what this one does about it: the queue, the receipts and the cap are the
    #: messaging package's; this shell supplies the three answers and the way to draw a waiting message.
    _relay: Relay
    #: What the last turn that ran to its end answered, or ``None`` when it did not end that way.
    _turn_answer: str | None
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
        self._start_inbox()
        if messenger is None:
            return
        messenger.receiver = self._relay_received
        # A reader's chat window (the web gateway) may send text to run as this window's own prompt.
        messenger.direct = True
        messenger.on_change = self._peers_changed
        messenger.on_conflict = self._messaging_conflict
        messenger.on_problem = self._messaging_problem
        self._messaging_live = True
        self._sync_messaging()
        self._messaging_start = asyncio.ensure_future(messenger.start())

    async def _stop_messaging(self) -> None:
        """Leave the broker. Nothing here may delay leaving."""
        messenger = self.messenger
        self._messaging_live = False
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
        session = self.client.session.id
        if self.client.session.locked:
            # Not this session's to answer for: a message sent to it would be a turn, which is a write.
            messenger.retire()
            self._messaging_session = session
            return
        if self._messaging_session not in (None, session) and self._relay.waiting:
            count = len(self._relay.waiting)
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
        """Take a message another session sent: start a turn, steer the running one, or hold it until this one is free.

        Called by the connection, on the loop, with the sender waiting for the answer; what it returns
        is what the sender's agent is told. It must not block.
        """
        if not self._messaging_live:
            return Receipt(False, "this session is closing")
        if self._updating:
            return Receipt(False, "this window is installing an update; try again when it is done")
        if self.client.session.locked:
            return Receipt(False, "this session is open in another ZettCode process, so it is read-only here")
        return self._relay.receive(relayed)

    def _relayed_waits(self, relayed: Relayed) -> None:
        """Draw one message that now waits for the request in flight to end."""
        preview = relayed.text.replace("\n", " ")
        if len(preview) > _PREVIEW:
            preview = preview[: _PREVIEW - 1] + "\u2026"
        self.transcript.notice(f"message from {relayed.sender} waits for this request to end: {preview}")
        self.app.invalidate()

    def _steer_relayed(self, relayed: Relayed) -> str | None:
        """Hand a message to the request in flight, if it is a turn that can take one.

        A direct chat window's message is never steered: the window is answered by the turn that message starts,
        and a turn somebody else started cannot answer it, so it waits like a follow-up. An accepted steer counts
        against the same limit the reader's own steering does — the run has one inbox, whoever filled it.

        Returns:
            The text the run will report the message by, or ``None`` when it was not handed over.
        """
        if relayed.direct or self._steer_blocked() is not None:
            return None
        key = self.client.session._steer_message(relayed.message())
        if key is None:
            return None
        self._steering_sent += 1
        return key

    def _adopted_relayed(self, text: str) -> Relayed | None:
        """Take the message the running request just adopted, if it was relayed, so its row can be drawn as one."""
        return self._relay.adopted(text)

    def _settle_relayed_steering(self) -> None:
        """After a request: messages it never adopted wait for the next turn rather than being lost.

        The relay keeps them, so this only lets it say so: a message that was interrupted after the run adopted it
        left when the run reported the adoption, and nothing the model has already read is ever run again.
        """
        self._relay.settle()

    def _start_inbox(self) -> None:
        """Give the runtime's inbox this shell's own way of starting a turn.

        One queue, one starter: an event from outside — a trigger, a plugin asking for itself, a program driving this
        client — and a message another session sent both wait in the runtime's inbox, and this is where they become
        turns. A message from another session keeps its richer path once it is started (the row in the transcript and
        the recovery of a steer the request never adopted), because the inbox hands the ``Relayed`` back in the item's
        payload and :meth:`_start_waiting` passes it to :meth:`_start_relayed`.
        """
        inbox = self._runtime_inbox()
        start = getattr(inbox, "start_with", None)
        if start is not None:
            start(self._start_waiting)

    def _start_waiting(self, item: object) -> bool:
        """Start one turn from a message the inbox held, and say whether it is under way.

        A message another session sent comes back with the ``Relayed`` in its payload, and runs the way it always has:
        drawn as that session's, answering a window when it is one. Anything else is a turn of the reader's own.
        """
        if self._busy:
            return False
        payload = getattr(item, "payload", None)
        if isinstance(payload, Relayed):
            self._start_relayed(payload)
            return True
        message = getattr(item, "message", "")
        text = message if isinstance(message, str) else getattr(message, "text", "")
        if not text.strip():
            return False
        self._set_busy(True)
        self._task = asyncio.create_task(self._run_prompt(text, (text,)))
        return True

    def _runtime_inbox(self):  # noqa: ANN201 - the Inbox class, imported lazily by the SDK client
        """Return the runtime's inbox, or ``None`` when the messaging part did not load."""
        return getattr(self.client, "inbox", None)

    def _start_relayed(self, relayed: Relayed) -> None:
        """Run one received message as a turn of its own."""
        # Busy before the task has run, exactly as for a follow-up: between here and its first step a
        # second message, or a keystroke, must not be able to start a turn beside this one.
        self._set_busy(True)
        if relayed.direct:
            self._task = asyncio.create_task(self._run_direct(relayed))
        else:
            self._task = asyncio.create_task(self._run_prompt(relayed.text, (relayed.text,), relayed=relayed))

    async def _run_direct(self, relayed: Relayed) -> None:
        """Run a chat window's text as this session's own prompt, then send the final answer back to the window."""
        from zettcode.sdk.types import DIRECT_EMPTY, DIRECT_UNFINISHED, IncomingMessage

        self._turn_answer = None
        await self._run_prompt(relayed.text, (relayed.text,))
        # This turn's own answer, not the last one in the conversation: a turn that failed or was stopped has none, and
        # the window is told so rather than handed the previous turn's words as this one's.
        answer = self._turn_answer
        message = IncomingMessage(
            sender_id=relayed.sender_id, sender=relayed.sender, text=relayed.text, via=relayed.via, hops=relayed.hops
        )
        if answer is None:
            await self.client.send_back(message, DIRECT_UNFINISHED)
        else:
            await self.client.send_back(message, answer if answer.strip() else DIRECT_EMPTY)

    def _start_next_relayed(self) -> bool:
        """Start the oldest waiting messages, if there are any and nothing is running.

        The ones that waited start as a single turn (see :func:`~zettcode.relay.batch_size`): a window that was busy
        answers them together instead of one turn each, and a chat window's message is always a turn of its own. The
        queue is the relay's; this only refuses while the window is installing an update.
        """
        if self._updating:
            return False
        return self._relay.start_next()
