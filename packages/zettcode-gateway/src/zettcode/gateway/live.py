"""The turns that are running now, as the gateway has heard them: what each has said so far, and which turn is which.

This is state only. It publishes nothing and waits for nothing: :class:`~zettcode.gateway.service.Gateway` feeds it what
a watched session said and tells the pages what came of it, because the gateway's event queue has one writer and it
stays there.

A turn is numbered when it is first seen. The number rides on every piece, on the end and on the snapshot a page reads,
so that a page can tell a snapshot of a turn that has since ended from one that is still running.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from zettcode.sdk.types import Peer, StreamEvent

#: The most of one turn's answer kept to show a page that opens in the middle of it, and how many tool calls.
TEXT_LIMIT = 200_000
TOOL_LIMIT = 40

#: A turn that has said nothing for this long while its session says it is idle is taken to have ended unseen.
STALE_SECONDS = 4.0


@dataclass
class Turn:
    """One running turn: its number, what it has said, and when it last said anything."""

    number: int
    at: float
    text: str = ""
    thinking: bool = False
    tools: list[dict[str, Any]] = field(default_factory=list)


class LiveTurns:
    """The running turn of each watched session, by session id.

    The clock is read on every use, so a caller may hand over a function that delegates to a clock it replaces later.
    Iterating yields the session ids of a copy, so a turn may be dropped while looping.
    """

    def __init__(self, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._turns: dict[str, Turn] = {}
        self._numbers = itertools.count(1)

    def __len__(self) -> int:
        return len(self._turns)

    def __iter__(self) -> Iterator[str]:
        return iter(list(self._turns))

    def number_of(self, session_id: str) -> int | None:
        """Return the number of the turn running in a session, or ``None`` when none is."""
        turn = self._turns.get(session_id)
        return None if turn is None else turn.number

    def hear(self, event: StreamEvent) -> dict[str, Any] | None:
        """Take one piece a session's turn said, and return what to tell the pages.

        A ``begin`` starts a turn afresh, whatever was running; any other piece of a session with no turn starts one,
        because the first pieces may have been missed. The caller reads an ``end`` itself (what the turn wrote has to be
        read before :meth:`finish` takes it away), so one that is passed here only returns ``None``.
        """
        session_id, kind = event.session_id, event.kind
        turn = self._turns.get(session_id)
        if kind == "begin":
            turn = self._turns[session_id] = Turn(next(self._numbers), self._clock())
        elif kind == "end":
            return None
        elif turn is None:
            turn = self._turns[session_id] = Turn(next(self._numbers), self._clock())
        turn.at = self._clock()
        wire: dict[str, Any] = {"kind": kind, "turn": turn.number}
        if kind == "text":
            turn.thinking = False
            turn.text = (turn.text + event.text)[-TEXT_LIMIT:]
            wire["text"] = event.text
        elif kind == "thinking":
            turn.thinking = True
        elif kind == "tool":
            turn.thinking = False
            turn.tools = [
                *turn.tools,
                {"id": event.call_id, "name": event.name, "brief": event.brief, "ok": None},
            ][-TOOL_LIMIT:]
            wire.update(id=event.call_id, name=event.name, brief=event.brief)
        elif kind == "tool_end":
            for tool in turn.tools:
                if tool["id"] == event.call_id:
                    tool["ok"] = event.ok
            wire.update(id=event.call_id, ok=event.ok)
        return wire

    def view(self, session_id: str) -> dict[str, Any] | None:
        """Return the turn running in a session as a page reads it, or ``None`` (the time it last spoke is not shown).

        ``tools`` is the turn's own list, not a copy: a ``tool_end`` heard later shows in a snapshot already taken, as
        it always has.
        """
        turn = self._turns.get(session_id)
        if turn is None:
            return None
        return {"turn": turn.number, "text": turn.text, "thinking": turn.thinking, "tools": turn.tools}

    def finish(self, session_id: str, number: int | None) -> bool:
        """Drop the turn ``number`` of a session; return whether it was still the one running.

        The session may have begun its next turn while the end was being read, and that one is not this one's to end.
        ``None`` (an end heard with no turn running) matches nothing, and neither does a session with no turn.
        """
        turn = self._turns.get(session_id)
        if turn is None or turn.number != number:
            return False
        del self._turns[session_id]
        return True

    def drop(self, session_id: str) -> int | None:
        """Forget a session's turn without ending it; return its number, or ``None`` when there was none."""
        turn = self._turns.pop(session_id, None)
        return None if turn is None else turn.number

    def drop_all(self) -> list[tuple[str, int]]:
        """Forget every turn, as after the broker was away and pieces were missed; return what was dropped."""
        dropped = [(session_id, turn.number) for session_id, turn in self._turns.items()]
        self._turns.clear()
        return dropped

    def expire(self, peers: Mapping[str, Peer]) -> list[tuple[str, int]]:
        """Drop a turn whose session has gone, or is idle and has been silent: its end was never heard.

        Returns the sessions and the turn each was running, for the caller to tell the pages.
        """
        now = self._clock()
        expired: list[tuple[str, int]] = []
        for session_id, turn in list(self._turns.items()):
            peer = peers.get(session_id)
            if peer is None or (peer.status != "working" and now - turn.at > STALE_SECONDS):
                del self._turns[session_id]
                expired.append((session_id, turn.number))
        return expired
