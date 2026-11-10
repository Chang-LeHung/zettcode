"""One chat message becomes one turn of the daemon, and the answer goes back where it came from.

The loop has two halves on purpose. Receiving is a long poll that must keep running — a turn can take minutes,
and a poll that stops while the agent thinks is a message the platform has to keep for us. So one task takes
messages off the platform as fast as they arrive, and one task runs them, one at a time, because there is one
daemon and one conversation behind it.

Everything that can go wrong has a sentence for the reader, because a chat app has no stack trace to show:

- the daemon is down and cannot start: how long until the next attempt, or what the start said;
- the broker is out of reach or the daemon refused the message;
- the daemon took it but has not answered: the answer is not lost, and the next message starts a fresh turn;
- the text is too long for one message: it is split, and the split points are on line breaks where it can;
- the same event delivered twice (a restart mid-batch): answered once;
- a sender who is not allowed to drive the agent: refused, with the id to allow;
- pictures: forwarded with the text they came with, and the ones that cannot go — too many, too large, a format the
  broker does not take — named back to the sender instead of lost quietly. A daemon whose model reads no pictures
  refuses the message itself, and that refusal is what the chat is told.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .guard import DaemonGuard, DaemonUnavailable
from .link import LinkError, SessionLink
from .state import BridgeState

logger = logging.getLogger(__name__)

#: Characters per outgoing message. Chat apps are generous but not unlimited, and a long answer that fails to
#: send is lost, so it is split below the limit rather than at it.
CHUNK = 3000

#: How often the daemon is looked at when no message is arriving, so a daemon that died is back before somebody
#: writes rather than after.
HEALTH_EVERY = 20.0

#: Seconds to wait before polling again after the platform itself failed.
POLL_BACKOFF = 5.0

#: Seconds one poll may stay out before it is dropped and asked again (see :meth:`Bridge._receive`).
POLL_TIMEOUT = 120.0


@dataclass(frozen=True, slots=True)
class BridgeSettings:
    """What the bridge allows and how it behaves.

    Args:
        allow: The user ids that may drive the agent. Empty means nobody: the agent has tools, and a bridge that
            answers a stranger is a shell a stranger can reach.
        allow_all: Accept every sender. For a bot nobody else can find; logged loudly when the bridge starts.
        chunk: Characters per outgoing message.
        health_every: Seconds between looks at the daemon when nothing is arriving.
    """

    allow: frozenset[str] = frozenset()
    allow_all: bool = False
    chunk: int = CHUNK
    health_every: float = HEALTH_EVERY
    #: Seconds a single poll may stay out before it is abandoned and asked again. The platform's long poll is under
    #: a minute; this is the width of the slack, not the poll's own timeout.
    poll_timeout: float = POLL_TIMEOUT

    def permits(self, user_id: str) -> bool:
        """Return whether this sender may drive the agent."""
        return self.allow_all or user_id in self.allow


@dataclass
class Bridge:
    """The chat side, the daemon, and the loop between them.

    Args:
        im: The platform client, already logged in (``agim``'s ``IMClient``).
        guard: The one daemon.
        link: The bridge's session on the broker.
        state: What has to survive a restart.
        path: Where ``state`` is written.
        settings: What it accepts and how it behaves.
        error: Where a change worth a reader's eye goes; the worker hands it the log.
    """

    im: Any
    guard: DaemonGuard
    link: SessionLink
    state: BridgeState
    path: Any
    settings: BridgeSettings = field(default_factory=BridgeSettings)
    error: Callable[[str], None] = logger.warning
    _incoming: asyncio.Queue = field(default_factory=asyncio.Queue, init=False, repr=False)
    _stopped: asyncio.Event = field(default_factory=asyncio.Event, init=False, repr=False)
    #: Messages whose answer could not be delivered, and how many times it was tried.
    _undelivered: dict[str, int] = field(default_factory=dict, init=False, repr=False)

    # -- the run --------------------------------------------------------------------------------------
    async def run(self) -> None:
        """Answer messages until :meth:`stop` is called or the platform goes away.

        A platform that fails to poll is retried after a pause; it is not a reason to leave, because a long poll
        that times out is normal and the next one usually has the message.
        """
        if not self.settings.allow and not self.settings.allow_all:
            self.error("no sender is allowed: every message will be refused until --allow names one")
        tasks = [
            asyncio.create_task(self._receive()),
            asyncio.create_task(self._answer()),
            asyncio.create_task(self._watch()),
        ]
        try:
            await self._stopped.wait()
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                try:
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001 - the run is ending anyway
                    pass

    def stop(self) -> None:
        """Leave after the message being answered."""
        self._stopped.set()

    # -- the two halves -------------------------------------------------------------------------------
    async def _receive(self) -> None:
        """Take messages off the platform and queue them; never run a turn here.

        The poll is given a deadline. The platform's long poll is under a minute, so a call that is still out after
        ``poll_timeout`` is not waiting for a message — it is a connection the network quietly dropped, and a bridge
        that keeps waiting on it is a bridge that never speaks again. The deadline turns that into one more poll.
        """
        while not self._stopped.is_set():
            try:
                result = await asyncio.wait_for(
                    self.im.receive(self.state.cursor or None), timeout=max(1.0, self.settings.poll_timeout)
                )
            except asyncio.TimeoutError:
                self.error(
                    f"nothing came back from the chat app in {int(self.settings.poll_timeout)} seconds; asking again"
                )
                continue
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 - a poll that fails is retried, not fatal
                self.error(f"receiving failed: {error}")
                await asyncio.sleep(POLL_BACKOFF)
                continue
            message = result.message
            # Every delivery is queued, duplicates included: the state is only written when an answer is done, so a
            # batch handed over twice can be in the queue twice, and it is `_turn` that sees it there.
            self._incoming.put_nowait((message, result.cursor))

    async def _answer(self) -> None:
        """Run queued messages one at a time: one daemon, one conversation, one turn."""
        while not self._stopped.is_set():
            message, cursor = await self._incoming.get()
            try:
                await self._turn(message, cursor)
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 - one bad message must not end the bridge
                self.error(f"answering {message.event_id} failed: {error}")

    async def _watch(self) -> None:
        """Bring the daemon back when it goes away, without a message having to arrive first."""
        while not self._stopped.is_set():
            await asyncio.sleep(max(1.0, self.settings.health_every))
            if self._stopped.is_set() or not self.state.session_id:
                continue
            try:
                await self.guard.ensure()
            except DaemonUnavailable as error:
                # Said once per failure at most: the guard already waited before this attempt, and a log line per
                # twenty seconds about a broken model key helps nobody.
                self.error(f"the daemon is not up: {error}")

    # -- one message ----------------------------------------------------------------------------------
    async def _turn(self, message: Any, cursor: str) -> None:
        """Answer one inbound message, and remember that it was answered."""
        if self.state.answered(str(message.event_id)):
            # The queue is a moment behind the state: a batch handed over twice may be queued twice before the
            # first answer is written. The state is the word, not the queue — but the cursor still moves, or the
            # next poll would ask for this message again.
            self.state.cursor = cursor or self.state.cursor
            self._save()
            return
        chat = str(message.chat_id)
        if not self.settings.permits(str(message.user_id)):
            self.error(f"refused {message.event_id}: {message.user_id} is not in the allowed senders")
            await self._say(
                chat, message, f"this chat is not allowed to use the agent. The sender id is {message.user_id}"
            )
            self._done(message, cursor)
            return
        prompt = _prompt(message)
        pictures, notes = _pictures(message)
        if notes:
            prompt = "\n".join([prompt, *(f"({note})" for note in notes)])
        if not message.text.strip() and not pictures and not notes:
            # Nothing to read and nobody to tell: no turn, no cost.
            await self._say(chat, message, "I cannot read that kind of message yet; send words or a picture.")
            self._done(message, cursor)
            return
        try:
            session = await self.guard.ensure()
        except DaemonUnavailable as error:
            await self._say(chat, message, self._unavailable(str(error)))
            self._done(message, cursor)
            return
        self.link.status("working")
        try:
            answer = await self.link.ask(session, prompt, images=pictures)
        except LinkError as error:
            self.error(f"the daemon did not answer {message.event_id}: {error}")
            await self._say(chat, message, f"I could not ask the agent: {error}")
            self._done(message, cursor)
            return
        finally:
            self.link.status("idle")
        if not answer.strip():
            answer = "the agent finished without an answer to send back."
        if await self._say(chat, message, answer):
            self._done(message, cursor)
            return
        # The answer exists and the chat will not take it. Answering the same message again would run the turn
        # again — and again, for as long as the platform keeps refusing — so the message is behind us after a
        # second attempt, and the log is where the reason is.
        attempts = self._undelivered.get(str(message.event_id), 0) + 1
        self._undelivered[str(message.event_id)] = attempts
        if attempts >= 2:
            self._undelivered.pop(str(message.event_id), None)
            self.error(f"giving up on delivering the answer to {message.event_id}: {attempts} attempts")
            self._done(message, cursor)

    def _unavailable(self, said: str) -> str:
        """Return what a chat is told when the daemon is not there."""
        wait = self.guard.wait_left()
        if wait > 0:
            return f"the agent is not running: {said}. I will try again in {int(wait) + 1} seconds."
        return f"the agent could not be started: {said}"

    async def _say(self, chat: str, message: Any, text: str) -> bool:
        """Send ``text`` to the chat in pieces; ``False`` when a piece did not go out.

        The reply context is the one this message carried, or the last one this chat had: a message that arrives
        without one (a refused attachment, for instance) should still be answered in the conversation it belongs to.
        """
        context = getattr(message, "reply_token", None) or self.state.reply_token(chat)
        for piece in split(text, self.settings.chunk):
            try:
                await self.im.send(chat, piece, context_token=context)
            except Exception as error:  # noqa: BLE001 - the chat is gone or the platform refused it
                self.error(f"sending to {chat} failed: {error}")
                return False
        return True

    def _done(self, message: Any, cursor: str) -> None:
        """Record the answer: the message is behind us, and the next poll starts after it."""
        self.state.remember(
            str(message.event_id), cursor=cursor or "", chat_id=str(message.chat_id), reply_token=message.reply_token
        )
        self._save()

    def _save(self) -> None:
        """Write the state, and say so if it cannot be written: a lost cursor is a re-answered batch."""
        try:
            self.state.save_runtime(self.path)
        except OSError as error:
            self.error(f"the state at {self.path} could not be written: {error}")


def _prompt(message: Any) -> str:
    """Return what the daemon is asked, with who said it; the pictures are gathered separately."""
    parts = [f"[chat {message.chat_id} from {message.user_id}]"]
    if message.text.strip():
        parts.append(message.text.strip())
    return "\n".join(parts)


def _pictures(message: Any) -> tuple[list[Any], list[str]]:
    """Return the pictures that can travel with the prompt, and a note for each one that cannot.

    The broker takes four pictures, four mebibytes each and eight together, in four formats. The limit is enforced
    there, so a message over it would be refused whole — text and all — which is why the count happens here: the
    text still goes, and the sender is told what stayed behind.
    """
    from zettcode.broker.protocol import IMAGE_TYPES, MAX_IMAGE_BYTES, MAX_IMAGES, MAX_IMAGES_BYTES, ImageData

    media = list(getattr(message, "media", ()) or ())
    pictures: list[ImageData] = []
    notes: list[str] = []
    total = 0
    for item in media:
        kind = str(getattr(item, "kind", "file"))
        if kind != "image":
            notes.append(f"1 {kind} not forwarded: only pictures and text reach the agent")
            continue
        media_type = str(getattr(item, "media_type", ""))
        data = bytes(getattr(item, "data", b""))
        if media_type not in IMAGE_TYPES:
            notes.append(f"1 picture not forwarded: {media_type or 'unknown type'} is not one the agent takes")
            continue
        if len(data) > MAX_IMAGE_BYTES:
            notes.append(f"1 picture not forwarded: {len(data) // (1 << 20)} MiB is over the 4 MiB limit")
            continue
        if len(pictures) >= MAX_IMAGES:
            notes.append(f"1 picture not forwarded: at most {MAX_IMAGES} go with one message")
            continue
        if total + len(data) > MAX_IMAGES_BYTES:
            notes.append("1 picture not forwarded: the pictures together are over 8 MiB")
            continue
        pictures.append(ImageData(media_type, data))
        total += len(data)
    refused = list(getattr(message, "rejected_media", ()) or ())
    if refused:
        notes.append(f"{len(refused)} attachment(s) the platform refused: too large")
    return pictures, notes


def split(text: str, limit: int) -> list[str]:
    """Split ``text`` into pieces of at most ``limit`` characters, on line breaks where it can.

    A single line longer than the limit is cut at the limit, which is the only place a reader may see a word
    broken in two; everything else starts a piece at a line break.
    """
    if limit <= 0:
        return [text]
    pieces: list[str] = []
    rest = text
    while len(rest) > limit:
        cut = rest.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        pieces.append(rest[:cut])
        rest = rest[cut:].lstrip("\n")
    pieces.append(rest)
    return [piece for piece in pieces if piece]


__all__ = ["Bridge", "BridgeSettings", "CHUNK", "HEALTH_EVERY", "POLL_BACKOFF", "split"]
