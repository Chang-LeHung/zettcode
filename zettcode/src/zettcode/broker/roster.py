"""Who is registered, what each can be called, and which one a typed name means.

Pure bookkeeping, with no sockets in it, so every rule about names can be tested by calling it.

A session is registered by the connection that holds it, and a connection holds at most one: the
shell's active session, which changes when the reader starts a new one or resumes another. Each
entry gets a *handle*, the word a person types after ``@``. It is made from the title, or from
the folder the session works in when it has no title yet, and kept unique, and it is stable: an
entry keeps its handle until its own title changes, so a name someone has just typed does not
move because another session arrived.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

from .protocol import KIND_ZETTCODE, PeerInfo, Refused, SessionUpdate
from .text import folder_name, short_id, slug, tail_id

#: Shortest prefix of a session id that names it. Shorter ones match too many to mean anything.
MIN_PREFIX = 4


@dataclass(slots=True)
class Entry:
    """One registered session.

    Attributes:
        owner: The connection that registered it.
        session_id: The store's id for the session.
        title: Its display title, possibly empty before it has been named.
        workspace: The directory it works in, so a reader can tell two sessions apart.
        status: ``"idle"`` or ``"working"``.
        handle: What follows the ``@`` to address it.
        kind: ``"zettcode"``, or ``"external"`` for a program that stands in for a session.
        order: Registration sequence, which is the order the roster lists them in.
    """

    owner: int
    session_id: str
    title: str
    workspace: str
    status: str
    handle: str
    order: int
    kind: str = KIND_ZETTCODE

    def public(self) -> PeerInfo:
        """Return the entry as the others see it."""
        return PeerInfo(self.session_id, self.handle, self.title, self.workspace, self.status, self.kind)


class Roster:
    """The registered sessions, by connection and by session id."""

    def __init__(self) -> None:
        self._by_owner: dict[int, Entry] = {}
        self._by_session: dict[str, int] = {}
        self._sequence = itertools.count(1)

    def __len__(self) -> int:
        return len(self._by_owner)

    def entries(self) -> list[Entry]:
        """Return every entry, in the order the sessions registered."""
        return sorted(self._by_owner.values(), key=lambda entry: entry.order)

    def snapshot(self) -> tuple[PeerInfo, ...]:
        """Return the roster as the broker pushes it to every connection."""
        return tuple(entry.public() for entry in self.entries())

    def of(self, owner: int) -> Entry | None:
        """Return the entry a connection holds, if any."""
        return self._by_owner.get(owner)

    def set(self, owner: int, update: SessionUpdate) -> Entry:
        """Register the session a connection holds, or replace the one it held.

        Raises:
            Refused: ``duplicate`` when another connection already holds this session. Two
                terminals that resumed the same session would each be sent every message addressed to
                it, and each would answer.
        """
        holder = self._by_session.get(update.session_id)
        if holder is not None and holder != owner:
            raise Refused("duplicate", "this session is already registered by another process")
        previous = self._by_owner.get(owner)
        if previous is not None:
            self._by_session.pop(previous.session_id, None)
        entry = Entry(
            owner=owner,
            session_id=update.session_id,
            title=update.title,
            workspace=update.workspace,
            status=update.status,
            handle="",
            kind=update.kind,
            order=previous.order
            if previous is not None and previous.session_id == update.session_id
            else next(self._sequence),
        )
        self._by_owner[owner] = entry
        self._by_session[update.session_id] = owner
        entry.handle = self._handle_for(
            entry, keep=previous.handle if previous and previous.session_id == update.session_id else None
        )
        return entry

    def drop(self, owner: int) -> Entry | None:
        """Forget what a connection held, and return it."""
        entry = self._by_owner.pop(owner, None)
        if entry is not None:
            self._by_session.pop(entry.session_id, None)
        return entry

    def resolve(self, target: object, *, asker: int | None = None) -> Entry:
        """Return the entry a typed name means.

        A name is, in this order: a session id, a handle, the start of a session id (at least
        :data:`MIN_PREFIX` characters), or a title. The first rule that matches anything decides:
        an id is never reinterpreted as a title because some title happens to look like it.

        Raises:
            Refused: ``unknown`` when nothing matches, ``ambiguous`` when a rule matches
                several (the message lists them, so the asker can pick one), ``self`` when the
                name is the asker's own session.
        """
        name = " ".join(target.split()).lower().lstrip("@") if isinstance(target, str) else ""
        if not name:
            raise Refused("unknown", "name a session: its handle, its id, or its title")
        entries = self.entries()
        rules = (
            [e for e in entries if e.session_id.lower() == name],
            [e for e in entries if e.handle == name],
            [e for e in entries if len(name) >= MIN_PREFIX and e.session_id.lower().startswith(name)],
            [e for e in entries if e.title and " ".join(e.title.split()).lower() == name],
        )
        for found in rules:
            if len(found) == 1:
                if asker is not None and found[0].owner == asker:
                    raise Refused("self", "a session cannot send a message to itself")
                return found[0]
            if found:
                listed = ", ".join(f"@{e.handle} ({e.title or 'untitled'})" for e in found)
                raise Refused("ambiguous", f"'{name}' matches several sessions: {listed}")
        raise Refused("unknown", f"no active session is called '{name}'")

    def _handle_for(self, entry: Entry, *, keep: str | None) -> str:
        """Return a handle for an entry that no other entry uses, and nothing else's id resembles.

        A handle that equals another session's id or its first eight characters would be
        resolved as that id (ids come first), so such a title gets a suffix like any other clash.
        """
        others = [other for other in self._by_owner.values() if other is not entry]
        taken = {other.handle for other in others}
        taken |= {other.session_id.lower() for other in others} | {short_id(other.session_id) for other in others}
        # What the reader can recognise, best first: what the session is about, the folder it works in,
        # and only then something that is merely unique.
        base = slug(entry.title) or slug(folder_name(entry.workspace)) or f"session-{tail_id(entry.session_id)}"
        if keep and (keep == base or keep.startswith(f"{base}-")) and keep not in taken:
            return keep
        if base not in taken:
            return base
        # The end of the id, not a number: the sessions that clash are the ones a reader already
        # cannot tell apart — two untitled ones in one folder — and a number says nothing about
        # which is which, while these six characters stay with the session however often the
        # terminals are restarted or the connections arrive in another order.
        stem = f"{base}-{tail_id(entry.session_id)}"
        if stem not in taken:
            return stem
        for number in itertools.count(2):
            candidate = f"{stem}-{number}"
            if candidate not in taken:
                return candidate
        raise AssertionError("unreachable")
