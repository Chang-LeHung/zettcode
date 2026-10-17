"""The two tools that let the model talk to the other ZettCode sessions running on this machine.

``list_sessions`` says who is there; ``send_message`` hands one of them a message. The other session
receives it as a turn of its own — drawn there as a message from this session, with this session's
id so that it can answer — and this call returns as soon as it has taken the message, not when it has
finished with it. What it does about the message is its own agent's business, and its answer, if any,
arrives here as a message of its own.

Both are request-scoped like every tool: they are registered for each request, and a request that is
a side question keeps only ``list_sessions`` (see :mod:`zettcode.app.agent.dialogue.side`), because
sending a message is not reading.
"""

from __future__ import annotations

from zett_agent.agent import AgentRunContext
from zett_agent.extensions.base import AgentExtension
from zett_agent.tools.base import AgentTool, tool

from zettcode.broker.client import SendError
from zettcode.broker.protocol import VIA_AGENT

from .messenger import Messenger

LIST_SESSIONS_TOOL_NAME = "list_sessions"
SEND_MESSAGE_TOOL_NAME = "send_message"

#: What a refused send says, by the reason the broker gave, for the ones a model can do something about.
_ADVICE = {
    "unknown": "No such session is active. Call list_sessions to see who is.",
    "ambiguous": "More than one session matches. Use the session id from list_sessions.",
    "self": "That is this session; a message to yourself is not sent.",
    "loop": "This conversation between sessions has gone on long enough; stop replying and tell your user.",
    "rate": "Too many messages were sent in a short time. Wait before sending another.",
    "offline": "The session broker is not running, so no other session can be reached right now.",
}


def _sentence(error: SendError) -> str:
    """Return what the model is told when a message did not arrive."""
    advice = _ADVICE.get(error.reason)
    if advice is None:
        return str(error)
    # Offline has nothing to add to what the advice says; the others carry the broker's own detail.
    return advice if error.reason == "offline" else f"{str(error).rstrip('.')}. {advice}"


class SessionMessagingExtension(AgentExtension):
    """Register ``list_sessions`` and ``send_message`` for a messenger."""

    def __init__(self, messenger: Messenger) -> None:
        """Keep the messenger the tools talk through."""
        self.messenger = messenger

    async def on_tool(self, context: AgentRunContext) -> None:
        """Register both tools for this request."""
        context.register_tool(self._list_tool())
        context.register_tool(self._send_tool())

    def _list_tool(self) -> AgentTool:
        """Create the tool that lists the other active sessions."""
        messenger = self.messenger

        @tool(name=LIST_SESSIONS_TOOL_NAME)
        async def list_sessions() -> str:
            """List the other ZettCode sessions that are running on this machine right now.
            Each line gives the name to address it by, its id, what it is about, whether it is idle or working,
            and the directory it works in. Sessions come and go, so the list is only true now.

            Snippet:
                list_sessions()

            Guidelines:
                - Call this before send_message when you do not already know the id of the session to message.
                - A session that is working still receives a message; it handles it when its current request ends.
                - Other sessions belong to the same user, but each one has its own conversation and its own files in mind.
            """
            others = messenger.peers()
            if not others:
                if messenger.connected:
                    return "No other ZettCode session is running."
                return "No other session can be seen: the session broker is not running."
            lines = [f"{len(others)} other session{'s' if len(others) != 1 else ''}:"]
            for entry in others:
                about = f'"{entry.title}"' if entry.title else "untitled"
                lines.append(f"- {entry.handle} (id {entry.session_id}) {about}, {entry.status}, in {entry.workspace}")
            return "\n".join(lines)

        return list_sessions

    def _send_tool(self) -> AgentTool:
        """Create the tool that sends a message to another active session."""
        messenger = self.messenger

        @tool(name=SEND_MESSAGE_TOOL_NAME)
        async def send_message(to: str, message: str) -> str:
            """Send a message to another running ZettCode session, which receives it as a request of its own.
            Returns once that session has taken the message, not once it has acted on it: its reply, if it
            sends one, arrives later as a message to you.

            Args:
                to: The session to message: its id from list_sessions, or the name listed beside it.
                message: What to tell it. It cannot see this conversation, so say everything it needs: what you
                    want, which files or facts matter, and what a useful answer looks like.

            Snippet:
                send_message(to="fix-parser", message="The tokenizer change is merged; please rerun your tests.")

            Guidelines:
                - Send a message only when your user asked you to, or when the work needs something only another session can do.
                - The other session cannot see this conversation, so write a message that stands on its own.
                - Do not send the same message twice; a message that was taken is being handled.
                - Do not reply to a message just to acknowledge it; reply when you have something to say that the sender needs.
                - Your answer to your own user is not sent to the other session; only this tool sends anything.
            """
            try:
                delivered = await messenger.send(to, message, via=VIA_AGENT)
            except SendError as error:
                raise ValueError(_sentence(error)) from error
            peer = delivered.to
            said = (
                "started on it now"
                if delivered.disposition == "started"
                else "queued it until its current request ends"
            )
            return f"Delivered to {peer.handle} (id {peer.session_id}); it {said}."

        return send_message


__all__ = ["LIST_SESSIONS_TOOL_NAME", "SEND_MESSAGE_TOOL_NAME", "SessionMessagingExtension"]
