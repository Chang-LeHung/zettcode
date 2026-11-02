"""Side questions: answers that never join the conversation.

A side question — "btw, what does this function do?" — runs in the same session,
so the model sees the conversation it is about, but nothing it produces joins it.
The store writes every message of that request with ``include_in_messages=False``,
the flag the runtime already defines as "record it, never replay it". Nothing has
to be undone in memory afterwards: the next request rebuilds its context from the
stored branch.

The tools are reading ones for the same reason. An edit made while asking a side
question would be invisible to the conversation that continues after it, so the
model would carry on with a false picture of the workspace.

Searching is one of them. The main agent searches with its shell and has no ``glob`` or ``grep``, but a side
question has no shell, so it is given the two search tools here.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from zett_agent.agent import AgentRunContext
from zett_agent.extensions.base import AgentExtension
from zett_agent.messages import UserMessage

#: Attribute marking the message a side question is asked as.
SIDE = "side"

#: Attribute (and stored tag) saying the reader watched the exchange on screen.
WATCHED = "watched"

#: Tools a side question may use: the ones that only read.
READ_ONLY_TOOLS = frozenset({"read", "read_file", "glob", "grep", "read_skill", "list_sessions", "message_history"})


def question(text: str, *, watched: bool = True) -> UserMessage:
    """Return the message a side question is asked as.

    Args:
        text: The question.
        watched: Whether the reader watched this question and its answer on screen. True for one they asked; False for
            one a plugin asks for itself, which is written down but belongs on no screen.
    """
    return UserMessage(content=text, attributes={SIDE: True, WATCHED: watched}, include_in_messages=False)


def is_side(message: object) -> bool:
    """Return whether a message is a side question."""
    return isinstance(message, UserMessage) and bool(getattr(message, "attributes", {}).get(SIDE))


def _watched(attributes: Mapping[str, Any]) -> bool:
    """Return whether a side question's attributes say the reader watched it.

    A question that does not say was asked before the tag existed. Those were the ones a reader asked — a plugin asking
    for itself is what this tag was added for — so the answer is True, and an older session keeps drawing them. It
    cannot be exact: a recap written by an older version is in those files as a side question too, and stays on their
    screen after a resume.
    """
    return bool(attributes.get(WATCHED, True))


def is_watched_side(message: object) -> bool:
    """Return whether a side question's message says the reader watched it, False for anything that is not one."""
    if not is_side(message):
        return False
    attributes = getattr(message, "attributes", None)
    return _watched(attributes) if isinstance(attributes, Mapping) else True


def is_side_run(context: AgentRunContext) -> bool:
    """Return whether the request being prepared is a side question."""
    # Read defensively: a request that never carried an input — a compaction pass
    # over a restored session, or a test's stand-in context — is not a side one.
    return is_side(getattr(context, "input_message", None))


def is_side_line(line: object) -> bool:
    """Return whether a stored line belongs to a side question.

    The store tags every line of that request, so a reader that walks the branch
    — the replay a resumed session builds, the HTML trace an export writes — can
    tell a side exchange from an ordinary one. The message's own
    ``include_in_messages`` flag would not do: instructions carry it too, and
    those are exactly what a trace wants to show.
    """
    tags = getattr(line, "tags", None)
    return isinstance(tags, Mapping) and bool(tags.get(SIDE))


def is_watched_side_line(line: object) -> bool:
    """Return whether a stored line belongs to a side question the reader watched on screen.

    A side question is drawn only when the front end began it — ``/btw`` is, a plugin's own question is not — and that
    is what the store writes down, so a resumed transcript restores what was on screen and nothing else. Lines written
    before this tag carry ``SIDE`` alone and are read as watched; see :func:`_watched` for why that is the closest
    a file can get to the truth.
    """
    if not is_side_line(line):
        return False
    tags = getattr(line, "tags", None)
    return _watched(tags) if isinstance(tags, Mapping) else True


class SideQuestions(AgentExtension):
    """Keep one side question's tools to reading.

    The shell marks the run it is about to start, because the hook that registers
    tools runs before the question itself is known. Pruning there rather than
    later matters twice over: the tool list is rebuilt for every request, and the
    guidance a prompt carries is written from that same list, so a write tool
    dropped now is never described to the model either.

    The question itself is a second signal, checked before every turn: it prunes
    the same tools if the mark was not set, which keeps a side question read-only
    even when something else starts it.
    """

    #: After the coding bundle, which is what registers the tools being filtered.
    priority = 120

    def __init__(self) -> None:
        """Start with no side question pending."""
        self._pending = False

    def begin(self) -> None:
        """Mark the run that is about to start as a side question."""
        self._pending = True

    def end(self) -> None:
        """Forget the mark, so the next run is an ordinary one."""
        self._pending = False

    @property
    def pending(self) -> bool:
        """Return whether a side question is the run in flight."""
        return self._pending

    async def on_tool(self, context: AgentRunContext) -> None:
        """Offer a side question the read tools only."""
        if self._pending:
            self._read_only(context)

    async def before_turn(self, context: AgentRunContext) -> None:
        """Prune again for a question that carried its own mark."""
        if is_side_run(context):
            self._read_only(context)

    @staticmethod
    def _read_only(context: AgentRunContext) -> None:
        """Drop every registered tool that is not one of the reading ones, and make sure the two search tools are there."""
        # Imported here: the tools bring the schema library, which a request that is not a side question never needs.
        from ..tools.files import glob, grep

        for name in tuple(context.tools):
            if name not in READ_ONLY_TOOLS:
                context.tools.pop(name, None)
        for search in (glob, grep):
            if search.name not in context.tools:
                context.register_tool(search)
