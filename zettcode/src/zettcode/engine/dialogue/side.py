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

#: Attribute (and stored tag) saying who asked a side question: ``/btw``, or a plugin's own ask.
ORIGIN = "origin"

#: The origin of a side question the reader asked, which is the one a resumed transcript restores by default.
READER = "reader"

#: Attribute (and stored tag) saying the reader watched the exchange on screen.
WATCHED = "watched"

#: Tools a side question may use: the ones that only read.
READ_ONLY_TOOLS = frozenset({"read", "read_file", "glob", "grep", "read_skill", "list_sessions", "message_history"})


def is_reader(origin: object) -> bool:
    """Return whether an origin names the reader, whose side questions are the ones a front end draws."""
    return origin == READER


def question(text: str, *, origin: str = READER, watched: bool | None = None) -> UserMessage:
    """Return the message a side question is asked as.

    Args:
        text: The question.
        origin: Who asked it — :data:`READER` for the reader's own ``/btw``, or the name of the plugin asking for
            itself (``"recap"``). It is written down with the exchange, and a resumed transcript restores only what the
            reader asked.
        watched: Whether the reader watched the question and its answer on screen. Left out, it follows ``origin``: a
            question the reader asked was drawn and comes back, a plugin's own was not. Pass it to override that, for a
            plugin that draws its own question on the reader's screen.
    """
    return UserMessage(
        content=text,
        attributes={SIDE: True, ORIGIN: origin, WATCHED: watched_by(origin, watched)},
        include_in_messages=False,
    )


def is_side(message: object) -> bool:
    """Return whether a message is a side question."""
    return isinstance(message, UserMessage) and bool(getattr(message, "attributes", {}).get(SIDE))


def _watched(values: Mapping[str, Any]) -> bool:
    """Return whether a side question's attributes — or a stored line's tags — say the reader watched it.

    ``watched`` is the answer, and it is written beside the origin on every new run, so it is what a stored exchange is
    read from. ``origin`` is not consulted here: it says who asked, for whoever reads the file later, and the two are
    written together, so a file that carries one without the other was not written by this program.

    Without ``watched`` the answer is no. That is the conservative reading, because the two errors are not equal:
    dropping an aside the reader saw costs a line of context, while restoring one they did not ask puts the model's own
    instructions in their mouth. Files from before both tags hold the recap's asks and the reader's ``/btw`` looking
    alike, and the only thing that asked on its own back then was the recap, so those are the lines this keeps off the
    screen; a ``/btw`` from such a file goes with them, which is the price of not keeping the recap's words.
    """
    return bool(values.get(WATCHED, False))


def watched_by(origin: str, watched: bool | None) -> bool:
    """Return whether a side question asked as ``origin`` was watched, when the caller left it out.

    A question the reader asked was drawn and comes back; a plugin's own was not. The one place this rule is written,
    for the message and for the request that carries it.
    """
    return is_reader(origin) if watched is None else watched


def is_watched_side(message: object) -> bool:
    """Return whether a side question's message says the reader watched it, False for anything that is not one."""
    if not is_side(message):
        return False
    # ``is_side`` read ``attributes.get`` a moment ago, so a side message always holds a mapping here; the default is
    # for the type checker, which sees only ``object``.
    return _watched(getattr(message, "attributes", {}))


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

    The tags record what the front end said when it asked, and that is what a resumed transcript restores. Two facts,
    not one: a question is drawn live only when the front end began a turn for it, which a plugin's own question never
    does — so a plugin that leaves the default is dropped live and would still come back after a reopen. What is
    restored is read from ``watched``, then from ``origin``, and from neither: a file written before both tags is not
    restored; see :func:`_watched` for why that is the cheaper error.
    """
    if not is_side_line(line):
        return False
    # ``is_side_line`` returned True, so the line carries tags.
    return _watched(line.tags)  # type: ignore[attr-defined]


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
