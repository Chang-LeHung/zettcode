"""The bridge's own session on the broker: one place to send a prompt, one place to hear the answer.

The daemon is a normal ZettCode session, so the bridge talks to it the way a chat window does: it registers a
session of its own, sends the text with ``direct`` set (the daemon runs it as its reader's prompt and answers
with ``send_back``), and waits for that answer here.

Only the daemon's answers are taken. Everything else on this session — another session writing to it, a group
message — is refused in words, because a bridge that answers everything would turn a stray message into a turn
of the agent the reader did not ask for.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field

from zettcode.broker.models import Incoming, Receipt, SendError, SessionInfo
from zettcode.broker.protocol import VIA_USER, ImageData


class LinkError(RuntimeError):
    """The message could not be handed to the daemon, and the message is what to tell the reader."""


logger = logging.getLogger(__name__)


#: What the answer queue carries when the connection, not the agent, ended the wait.
_LOST = object()


@dataclass
class SessionLink:
    """The bridge's line to the daemon, over the session broker.

    Args:
        session_id: The id this bridge registers under. It only has to be stable; the roster shows the handle.
        handle: What other sessions call the bridge, in the roster and in the daemon's prompt.
        workspace: The directory named in the roster beside this session.
        timeout: Seconds to wait for the daemon's answer after it has taken a message.
    """

    session_id: str
    handle: str = "chat-bridge"
    workspace: str = ""
    timeout: float = 600.0
    _client: object | None = field(default=None, init=False, repr=False)
    _answers: asyncio.Queue[object] = field(default_factory=asyncio.Queue, init=False, repr=False)
    _waiting: bool = field(default=False, init=False, repr=False)
    #: The session this bridge is waiting on, so another session's message cannot be taken for its answer.
    _asking: str = field(default="", init=False, repr=False)
    #: What the broker said when the connection went out of reach, while a turn was waiting.
    _problem: str = field(default="", init=False, repr=False)

    # -- the life of the line -------------------------------------------------------------------------
    async def start(self) -> None:
        """Join the broker. Without one, every send says so rather than hanging."""
        from zettcode.broker.client import BrokerClient

        client = BrokerClient(on_message=self._heard, on_problem=self._trouble, on_conflict=self._conflict)
        self._client = client
        await client.start()
        client.set_session(
            SessionInfo(session_id=self.session_id, title=self.handle, workspace=self.workspace, status="idle")
        )

    async def close(self) -> None:
        """Leave the broker. Safe to call twice, and safe when it never joined."""
        client = self._client
        self._client = None
        if client is not None:
            await client.close()  # type: ignore[attr-defined]

    async def connected(self, timeout: float = 10.0) -> bool:
        """Return whether the broker is reachable, waiting a moment for a connection that is on its way."""
        client = self._client
        if client is None:
            return False
        return bool(await client.wait_connected(timeout))  # type: ignore[attr-defined]

    def status(self, status: str) -> None:
        """Say whether a turn is running, so the roster tells the truth about this session."""
        client = self._client
        if client is None:
            return
        client.set_session(  # type: ignore[attr-defined]
            SessionInfo(session_id=self.session_id, title=self.handle, workspace=self.workspace, status=status)
        )

    # -- one prompt, one answer -----------------------------------------------------------------------
    async def ask(self, session: str, text: str, *, images: Sequence[ImageData] = ()) -> str:
        """Send ``text`` to ``session`` as this reader's own words and return the answer it sends back.

        Pictures travel with it. A ``direct`` message is the only one the broker lets carry them, which is what
        this is: the daemon puts them into the same prompt the text becomes.

        Raises:
            LinkError: The broker or the daemon refused the message, or the answer did not come in time.
        """
        client = self._client
        if client is None:
            raise LinkError("the chat bridge is not connected to the session broker")
        while not self._answers.empty():  # an answer that arrived after its timeout belongs to nobody
            self._answers.get_nowait()
        self._waiting = True
        self._asking = session
        self._problem = ""
        try:
            await self._hand_over(client, session, text, images)
        except SendError as error:
            self._waiting = False
            self._asking = ""
            raise LinkError(_sentence(error)) from error
        except Exception as error:  # noqa: BLE001 - a lost connection reads as a send that did not happen
            self._waiting = False
            self._asking = ""
            raise LinkError(f"the message did not reach the daemon: {error}") from error
        try:
            answer = await asyncio.wait_for(self._answers.get(), timeout=self.timeout)
        except asyncio.TimeoutError as error:
            raise LinkError(
                f"the daemon took the message but did not answer in {int(self.timeout)} seconds; it may still be "
                "working on it, and an answer after this is not forwarded"
            ) from error
        finally:
            self._waiting = False
            self._asking = ""
        if answer is _LOST:
            raise LinkError(self._problem or "the connection to the session broker was lost while the agent answered")
        return str(answer)

    async def _hand_over(self, client: object, session: str, text: str, images: Sequence[ImageData]) -> None:
        """Send the prompt, giving a daemon that has just restarted a moment to appear in the roster.

        A daemon that was started or resumed is in its record before it is registered with the broker, so the first
        send can be refused as ``unknown`` while the process is perfectly healthy. Three tries a second apart is
        the difference between that and a sentence about a session that does not exist.
        """
        tries = 3
        for attempt in range(tries):
            try:
                await client.send(  # type: ignore[attr-defined]
                    session,
                    self._shorten(text, client),
                    direct=True,
                    mode="followup",
                    via=VIA_USER,
                    images=list(images),
                )
                return
            except SendError as error:
                if error.reason in {"unknown", "gone"} and attempt + 1 < tries:
                    await asyncio.sleep(1.0 * (attempt + 1))
                    continue
                raise

    async def send(self, session: str, text: str) -> None:
        """Tell a session something without waiting for an answer — a note, not a prompt."""
        client = self._client
        if client is None:
            return
        try:
            await client.send(session, self._shorten(text, client), mode="followup", via=VIA_USER)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - a note that cannot be delivered is not worth failing a turn over
            return

    # -- what the broker calls ------------------------------------------------------------------------
    def _heard(self, message: Incoming) -> Receipt:
        """Take one message: the daemon's answer goes to the turn waiting for it, anything else is refused.

        Only the session that was asked may answer. Another session — a stray ``send_message`` from an agent, a
        group message — would otherwise be forwarded to the chat as if the agent had said it, and the real answer
        would be refused as a second one.
        """
        if not self._waiting:
            return Receipt(accepted=False, reason="this is a chat bridge; it is not reading messages right now")
        if message.group or message.sender.session_id != self._asking:
            return Receipt(
                accepted=False,
                reason="this bridge is waiting for the daemon's answer, not for another session's message",
            )
        self._answers.put_nowait(message.text)
        return Receipt(accepted=True, disposition="delivered")

    def _trouble(self, problem: str | None) -> None:
        """A connection that is out of reach ends the wait instead of leaving the chat hanging.

        The wait is ended with a marker, not with an empty answer: an empty string is what a silent agent looks
        like, and telling the reader the agent finished when the broker merely dropped is a lie.
        """
        if problem is not None and self._waiting:
            self._problem = problem
            self._answers.put_nowait(_LOST)

    def _conflict(self, message: str | None) -> None:
        """Another process holds this bridge's session on the broker; say so where the worker's log is."""
        if message is not None:
            logger.warning("another process holds this bridge's session on the broker: %s", message)

    @staticmethod
    def _shorten(text: str, client: object) -> str:
        """Return ``text`` fitted to what the broker takes in one message."""
        limits = getattr(client, "limits", None)
        room = int(getattr(limits, "max_text", 0) or 0)
        if room <= 0 or len(text) <= room:
            return text
        marker = f"\n[\u2026 {len(text) - room} characters not sent: the broker takes {room} in one message]"
        return text[: max(0, room - len(marker))] + marker


def _sentence(error: SendError) -> str:
    """Return what a refused send means for the reader, rather than the broker's code alone."""
    reason = getattr(error, "reason", "") or "refused"
    if reason == "gone":
        return "the daemon is not connected to the session broker"
    if reason == "unknown":
        return "the daemon's session is not registered with the session broker"
    if reason == "denied":
        return "the daemon refused the message"
    if reason == "too_long" and "picture" in str(error):
        return f"the pictures were refused: {error}"
    if reason == "invalid" and "picture" in str(error):
        return f"the pictures were refused: {error}"
    return f"the message was not delivered ({reason}): {error}"


__all__ = ["LinkError", "SessionLink"]
