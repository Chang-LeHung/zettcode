"""``@`` references: resources a draft can pull into one message.

A mention is a token like ``@code-review`` typed in the composer. A provider
owns one kind of resource (other sessions here; files in ``zettcode-files``, skills in ``zettcode-skills``) and both
lists candidates for the completion menu and expands a token into the text the model
should see. The draft the user typed stays the message that is stored and
shown; the expansion is carried as a message attribute, so a session loaded
later restores the original text instead of the injected resource.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from zettcode.broker.text import folder_name
from zettcode.mention import Mention, MentionProvider, MentionRegistry
from zettcode.wire import RosterPeer

__all__ = [
    "Mention",
    "MentionProvider",
    "MentionRegistry",
    "RosterPeer",
    "SessionMentions",
]


class SessionMentions(MentionProvider):
    """The other ZettCode sessions that are running, addressed by the name they are listed under.

    A session named anywhere in a draft is a reference like any other: the model reads ``session "name"``
    and is told how to reach that session, and decides for itself whether the request calls for a message.
    The shell sends nothing itself (see :mod:`zettcode.app.ui.messaging`).

    Candidates are read from what the connection last reported — a list in memory — and never from
    the broker: completion runs on every keystroke after an ``@``.
    """

    kind = "session"
    #: A session is the most specific thing a name can mean, ahead of a skill and a file.
    precedence = -20

    def __init__(self, peers: Callable[[], Sequence[RosterPeer]]) -> None:
        """Offer whichever sessions ``peers`` returns when asked.

        Args:
            peers: The other sessions as of now; called for every query, so it must not block.
        """
        self._peers = peers

    def candidates(self, query: str) -> Sequence[Mention]:
        """List the sessions ``query`` could mean, the likeliest first.

        A reader looks for a session by what they remember of it, which is its name, what it was about,
        the folder it works in, or the start of its id — so any of those matches, with a session whose
        *name* starts with the query before one that only mentions it elsewhere. The token offered is
        always the name, because that is what can be sent to.
        """
        lowered = query.lower()
        ranked: list[tuple[int, int, RosterPeer]] = []
        for order, peer in enumerate(self._peers()):
            if peer.handle.lower().startswith(lowered):
                ranked.append((0, order, peer))
            elif (
                lowered in peer.handle.lower() or lowered in peer.title.lower() or lowered in self._folder(peer).lower()
            ):
                ranked.append((1, order, peer))
            elif len(lowered) >= 4 and peer.session_id.lower().startswith(lowered):
                ranked.append((2, order, peer))
        return tuple(
            Mention(token=f"@{peer.handle}", kind=self.kind, name=peer.handle, description=self._describe(peer))
            for _, _, peer in sorted(ranked, key=lambda item: item[:2])
        )

    @staticmethod
    def _folder(peer: RosterPeer) -> str:
        """Return the last part of the directory the session works in."""
        return folder_name(peer.workspace)

    @classmethod
    def _describe(cls, peer: RosterPeer) -> str:
        """Return the menu's line for a session: what it is about, whether it is working, where it is."""
        parts = [peer.title or "untitled"]
        if peer.status != "idle":
            parts.append(peer.status)
        folder = cls._folder(peer)
        if folder:
            parts.append(folder)
        return " \u00b7 ".join(parts)

    def rename(self, name: str) -> str | None:
        """Put ``session "work"`` where the reader typed ``@work``: the model has no use for the ``@``."""
        return f'session "{name}"' if self._find(name) is not None else None

    def _find(self, name: str) -> RosterPeer | None:
        """Return the session called ``name`` among those running now."""
        return next((peer for peer in self._peers() if peer.handle == name), None)

    def expand(self, name: str) -> str | None:
        """Tell the model what the reader's ``@`` meant and how to reach that session.

        Nothing is sent from here: the model is told which session the words mean and how to reach it, and
        decides for itself whether the request calls for a message. A draft that begins with the name is no
        different from one that names the session inside a sentence.
        """
        peer = self._find(name)
        if peer is None:
            return None
        where = f" in {peer.workspace}" if peer.workspace else ""
        about = f' It is titled "{peer.title}".' if peer.title else ""
        return (
            f'In the message above, `session "{name}"` is what the user wrote as @{name}. In ZettCode an @ before a '
            f"name means another ZettCode session that is running right now, not a file or a skill. This one works{where}.{about}\n"
            f"When the user's message is addressed to that session — the @ begins the message — what follows the name "
            f"is the message to pass on. When the session is only mentioned, decide whether the request is for it. "
            f'To send, call the send_message tool: send_message(to="{peer.session_id}", message=...). Write the '
            f"message so the other session can act on it without having seen this conversation. If the request is only "
            f"about the session (what it is doing, where it is), list_sessions answers that. Do not send anything the "
            f"user did not ask you to pass on."
        )
