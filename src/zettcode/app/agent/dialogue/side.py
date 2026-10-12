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
"""

from __future__ import annotations

from collections.abc import Mapping

from zett_agent.agent import AgentRunContext
from zett_agent.extensions.base import AgentExtension
from zett_agent.messages import UserMessage

#: Attribute marking the message a side question is asked as.
SIDE = "side"

#: Tools a side question may use: the ones that only read.
READ_ONLY_TOOLS = frozenset({"read_file", "view_image", "glob", "grep", "read_skill"})


def question(text: str) -> UserMessage:
    """Return the message a side question is asked as."""
    return UserMessage(content=text, attributes={SIDE: True}, include_in_messages=False)


def is_side(message: object) -> bool:
    """Return whether a message is a side question."""
    return isinstance(message, UserMessage) and bool(getattr(message, "attributes", {}).get(SIDE))


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
        """Drop every registered tool that is not one of the reading ones."""
        for name in tuple(context.tools):
            if name not in READ_ONLY_TOOLS:
                context.tools.pop(name, None)
