"""Sessions: which one is active, switching and forking, and the title that names it.

Resuming is two steps on purpose. :meth:`SessionsMixin.load_session` reads and replays a
stored session into a value and touches nothing the shell is reading, so the shell can run
it on a worker thread; :meth:`SessionsMixin.install_session` only assigns, so it runs where
the rest of the shell does.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from zett_agent.messages import AssistantMessage, UserMessage
from zett_agent.model import ReasoningEffort

from zettcode.engine.dialogue.title import summarize_title
from zettcode.engine.extensions.usage import UsageSnapshot, session_usage
from zettcode.engine.storage import Session, SessionInfo, SessionStats
from zettcode.wording import UNTITLED_SESSION

from .context import ContextMixin


@dataclass(frozen=True, slots=True)
class StoredSession:
    """A session read from the store, not yet made active.

    Attributes:
        session_id: The session that was read.
        session: Its parsed file.
        usage: Totals accumulated from the usage every stored reply recorded.
        title: Its stored display title, if it has one: read here because folding
            the metadata log is the other thing resuming used to do on the loop.
        model: The model the session last used, by the name the model picker shows, if one
            was recorded; read here for the same reason as the title.
    """

    session_id: str
    session: Session
    usage: UsageSnapshot
    title: str | None
    model: str | None = None


class SessionsMixin(ContextMixin):
    """Switch, resume, fork, list, and name the conversation the next turn belongs to."""

    @property
    def session_title(self) -> str | None:
        """Return the active session's stored display title, if it has one.

        Reading the store folds the whole metadata log, so callers that paint
        often should cache the result instead of asking once per frame.
        """
        return self.runtime.persistence.session_title(self.session_id)

    def session_path(self) -> Path:
        """Return the file this session is stored in, under the store root.

        The whole conversation, on disk: what ``/context`` shows beside the token
        breakdown, and what a reader opens when they want the raw records rather
        than a rendered transcript.
        """
        return self.runtime.persistence.session_path(self.session_id)

    @property
    def session_name(self) -> str:
        """Return the name to show for the active session.

        A session is named after its first reply; until then the store has no
        title, and a status line or list row that shows nothing at all reads
        like a bug rather than like a fresh session.
        """
        return self.session_title or UNTITLED_SESSION

    def new_session(self) -> str:
        """Start a new conversation."""
        return self.runtime.new_session()

    def use_session(self, session_id: str) -> None:
        """Switch future turns to a session."""
        self.runtime.use_session(session_id)

    def fork_session(self) -> str:
        """Copy this conversation's context into a new session, and return its id.

        What is carried over is what a request would send — the newest checkpoint's
        summary and the messages after it — not the whole stored history: the fork
        starts from the conversation the model is actually working with. The shell
        installs the result the way a resume does, so the reader lands in the fork
        with the same conversation in front of them.

        Synchronous file work on purpose, so the shell can run it on a thread.
        """
        return self.runtime.persistence.fork(self.session_id)

    def load_session(self, session_id: str) -> StoredSession:
        """Read a stored session, changing nothing.

        This is the expensive half of resuming — parsing the file and adding up its usage — and it touches no
        state anyone is reading, so a caller may run it on a worker thread and hand the result to
        :meth:`install_session` on the loop. What a front end shows of the session it builds from
        ``stored.session`` itself.

        Raises:
            ValueError: The store holds no such session, or its file is corrupt.
        """
        persistence = self.runtime.persistence
        session = persistence.read(session_id)
        if session.header is None:
            raise ValueError(f"Unknown session: {session_id}")
        return StoredSession(
            session_id=session_id,
            session=session,
            usage=session_usage(session.branch()),
            title=persistence.session_title(session_id),
            model=persistence.session_model(session_id),
        )

    def install_session(self, stored: StoredSession) -> None:
        """Make a loaded session the active one: its totals, its id, its model.

        The cheap half, and the one that changes state; everything it does is assignment.
        """
        session_id, session = stored.session_id, stored.session
        self.runtime.usage.seed(session_id, stored.usage)
        self.use_session(session_id)
        # Pick up where the session left off: the model it last used, when this configuration
        # still has it. A session that never recorded one, or whose model is gone, keeps whatever
        # is selected now — the shell says so in the second case.
        model = self.runtime.find_model(stored.model) if stored.model else None
        if model is not None and model is not self.runtime.active_model:
            self.runtime.use_model(model)
        # Prime the report with what the next turn would send, not with what the
        # transcript shows: the display keeps every message a compaction folded
        # away, and measuring those claims a request several times the size of the
        # real one — 2.9 M tokens against a context of 290 k, which is a share
        # pinned at a hundred. `_context_request` is the one definition of that
        # request; the environment and tool notes only exist inside a real one,
        # which the report admits.
        #
        # It is handed over as a function, not built here: the request holds every
        # message since the last checkpoint, decoding them is most of what a long
        # resume would cost, and nothing reads the list until `/context` does.
        self.runtime.context.remember(session_id, lambda: self._stored_request(session))

    def restore_session(self, session_id: str) -> None:
        """Load the stored branch and make it the active one."""
        self.install_session(self.load_session(session_id))

    async def list_sessions(self, *, limit: int = 20) -> list[SessionInfo]:
        """List persisted session metadata by recent activity."""
        return await self.runtime.persistence.list_sessions(limit=limit)

    async def session_stats(self, sessions: Sequence[SessionInfo]) -> dict[str, SessionStats]:
        """Return the entry count and token totals of listed sessions, keyed by session id.

        A session missing from the answer has no totals to show.
        """
        return await self.runtime.persistence.session_stats([session.session_id for session in sessions])

    async def rename_session(self, title: str) -> str:
        """Store a display title for the active session and return it cleaned.

        A title the user typed wins over the one the background summarizer would
        have written: ``title_session`` never renames a session that already has
        a title, so naming by hand also stops the model call.

        Args:
            title: Name to store; surrounding space is trimmed, and a blank or
                over-long name is rejected by the store.

        Raises:
            SessionLocked: Another process has this session open.
        """
        self.require_session()
        await self.runtime.persistence.set_title(self.session_id, title)
        return title.strip()

    async def title_session(self, session_id: str) -> str | None:
        """Name a session from its first exchange, unless it already has a title.

        The call is a background nicety: it reads the stored branch, asks the
        active model for a short title, and appends that title to the session.

        Args:
            session_id: Session to name.

        Returns:
            The stored title, or ``None`` when the session was already named, has
            no first exchange yet, or the model replied with nothing usable.
        """
        if self.runtime.persistence.session_title(session_id) is not None:
            return None
        if session_id == self.session_id and self.session_locked:
            return None  # a nicety, and not one that is worth writing into a session that is not ours
        session = self.runtime.persistence.read(session_id)
        branch = session.branch()
        question = next(
            (line.message[0].text for line in branch if isinstance(line.message[0], UserMessage)),
            None,
        )
        answer = next(
            (line.message[0].content for line in reversed(branch) if isinstance(line.message[0], AssistantMessage)),
            None,
        )
        if not question or not answer:
            return None
        await self.runtime.start()
        # A level the model takes, so naming the session cannot be what fails on an endpoint that lacks `low`.
        effort = self.runtime.required_model.accepted_effort(ReasoningEffort.LOW)
        title = await summarize_title(self.runtime.provider, question=question, answer=answer, effort=effort)
        if title is None:
            return None
        await self.runtime.persistence.set_title(session_id, title)
        return title
