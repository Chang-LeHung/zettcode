"""The tools that let the model talk to the other ZettCode sessions running on this machine.

``list_sessions`` says who is there, and which group chats this session may write to; ``send_message`` hands one of
them a message, or every member of a group; ``message_history`` reads what this session and another one (or a group)
said to each other before, from the broker's persistent store; ``manage_group`` makes and changes group chats. The other session
receives it as a turn of its own — drawn there as a message from this session, with this session's
id so that it can answer — and this call returns as soon as it has taken the message, not when it has
finished with it. A message asks for one of two things while that session is busy: it can be handed to
the request it is running (``mode="steer"``, the default) or wait until that request ends
(``mode="followup"``); an idle session starts a turn either way. What it does about the message is its
own agent's business, and its answer, if any, arrives here as a message of its own.

All are request-scoped like every tool: they are registered for each request, and a request that is a side
question keeps only ``list_sessions`` and ``message_history`` (see :mod:`zettcode.engine.dialogue.side`), because
sending a message is not reading.
"""

from __future__ import annotations

import time

from zett_agent.agent import AgentRunContext
from zett_agent.extensions.base import AgentExtension
from zett_agent.tools.base import AgentTool, tool

from zettcode.broker.client import SendError
from zettcode.broker.protocol import VIA_AGENT
from zettcode.engine.messenger import Messenger
from zettcode.modes import MODE_STEER, MODES

LIST_SESSIONS_TOOL_NAME = "list_sessions"
SEND_MESSAGE_TOOL_NAME = "send_message"
MESSAGE_HISTORY_TOOL_NAME = "message_history"
MANAGE_GROUP_TOOL_NAME = "manage_group"

#: The most characters of one stored message ``message_history`` shows; a longer one is cut, with its length.
HISTORY_TEXT = 600

#: What a refused send says, by the reason the broker gave, for the ones a model can do something about.
_ADVICE = {
    "unknown": "No such session is active. Call list_sessions to see who is.",
    "ambiguous": "More than one session matches. Use the session id from list_sessions.",
    "self": "That is this session; a message to yourself is not sent.",
    "loop": "This conversation between sessions has gone on long enough; stop replying and tell your user.",
    "rate": "Too many messages were sent in a short time. Wait before sending another.",
    "offline": "The session broker is not running, so no other session can be reached right now.",
    "denied": "You are not a member of that group. list_sessions shows the groups you may write to.",
    "gone": "Nobody there is connected right now.",
    "internal": "The broker failed while delivering that. Try again; if it keeps failing, tell your user.",
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
        context.register_tool(self._history_tool())
        context.register_tool(self._group_tool())

    def _list_tool(self) -> AgentTool:
        """Create the tool that lists the other active sessions."""
        messenger = self.messenger

        @tool(name=LIST_SESSIONS_TOOL_NAME)
        async def list_sessions() -> str:
            """List the other ZettCode sessions that are running on this machine right now, and the group chats
            this session is a member of (the only ones it may write to).
            Each session line gives the name to address it by, its id, what it is about, whether it is idle or working,
            and the directory it works in; each group line gives #name and its members. Sessions come and go, so the
            list is only true now.

            Snippet:
                list_sessions()

            Guidelines:
                - Call this before send_message when you do not already know the id of the session to message.
                - A session that is working still receives a message; it handles it when its current request ends.
                - Other sessions belong to the same user, but each one has its own conversation and its own files in mind.
            """
            others = messenger.peers()
            groups = messenger.groups()
            if not others and not groups:
                if messenger.connected:
                    return "No other ZettCode session is running."
                return "No other session can be seen: the session broker is not running."
            lines = []
            if others:
                lines.append(f"{len(others)} other session{'s' if len(others) != 1 else ''}:")
            else:
                lines.append("No other ZettCode session is running.")
            for entry in others:
                about = f'"{entry.title}"' if entry.title else "untitled"
                lines.append(f"- {entry.handle} (id {entry.session_id}) {about}, {entry.status}, in {entry.workspace}")
            if groups:
                names = {entry.session_id: entry.handle for entry in messenger.client.roster}
                lines.append(f"{len(groups)} group chat{'s' if len(groups) != 1 else ''} you may write to:")
                for group in groups:
                    members = ", ".join(names.get(m, f"{m[:8]} (offline)") for m in group.members)
                    lines.append(f"- #{group.name}: {members}")
            return "\n".join(lines)

        return list_sessions

    def _send_tool(self) -> AgentTool:
        """Create the tool that sends a message to another active session."""
        messenger = self.messenger

        @tool(name=SEND_MESSAGE_TOOL_NAME)
        async def send_message(to: str = "", message: str = "", mode: str = MODE_STEER, group: str = "") -> str:
            """Send a message to another running ZettCode session, or to every other member of a group chat you are
            in. The receiver gets it as a request of its own. Returns once they have taken the message, not once
            they have acted on it: a reply, if one is sent, arrives later as a message to you. Every message costs its
            receiver a turn, so send one only when it changes what they will do.

            Args:
                message: What to tell them. They cannot see this conversation, so say everything they need: what you
                    want, which files or facts matter, and what a useful answer looks like.
                to: The session to message: its id from list_sessions, or the name listed beside it. Give this or group.
                group: A group chat to write to instead, such as "review" (as listed by list_sessions, without the
                    #). Every other member that is connected receives the message, and everyone can read it.
                mode: What a busy receiver should do. "steer" (the default) hands the message to the request it is
                    running, so it changes course now; "followup" waits until that request ends. A session that is
                    idle starts on the message either way.

            Snippet:
                send_message(to="fix-parser", message="The tokenizer change is merged; please rerun your tests.")
                send_message(to="fix-parser", message="Also check the tab case.", mode="followup")
                send_message(group="review", message="Round one is done; findings are in docs/review.md.")

            Guidelines:
                - Send a message only when your user asked you to, or when the work needs something only another session can do.
                - The receiver cannot see this conversation, so write a message that stands on its own.
                - Do not send the same message twice; a message that was taken is being handled.
                - Reply only when the message needs an answer: it asks a question, asks you to do something, or you have a result, a blocker or a decision the sender is waiting for. Otherwise stay silent.
                - Never send thanks, "got it", "ok", "done", "bye" or any other closing courtesy, and do not answer one you receive: a conversation ends when nobody needs anything more, and replying to a goodbye starts a loop that costs tokens for both sides.
                - When the work is finished, send one message with the result if someone is waiting for it, then stop. Do not confirm that you sent it.
                - Write to a group only when all of its members need to know; otherwise message one session. In a group, do not reply just because you were addressed: answer only when you are the one who has what was asked for, and never echo agreement that others have already given.
                - Your answer to your own user is not sent to the other session; only this tool sends anything.
            """
            if mode not in MODES:
                raise ValueError("mode is 'steer' or 'followup'")
            if not message.strip():
                raise ValueError("a message needs some text")
            if bool(to) == bool(group):
                raise ValueError("give exactly one of 'to' (a session) or 'group' (a group chat)")
            try:
                if group:
                    sent = await messenger.send_group(group, message, via=VIA_AGENT, mode=mode)
                    names = ", ".join(peer.handle for peer, _ in sent.delivered)
                    note = f"; not delivered to {', '.join(h for h, _ in sent.failed)}" if sent.failed else ""
                    return f"Delivered to #{sent.group}: {names}{note}."
                delivered = await messenger.send(to, message, via=VIA_AGENT, mode=mode)
            except SendError as error:
                raise ValueError(_sentence(error)) from error
            peer = delivered.to
            said = {
                "started": "started on it now",
                "steered": "steered it into the request it was running",
                "queued": "queued it until its current request ends",
                "delivered": "delivered it to that session's chat window",
            }.get(delivered.disposition, "took it")
            return f"Delivered to {peer.handle} (id {peer.session_id}); it {said}."

        return send_message

    def _history_tool(self) -> AgentTool:
        """Create the tool that reads what was said before."""
        messenger = self.messenger

        @tool(name=MESSAGE_HISTORY_TOOL_NAME)
        async def message_history(session: str = "", group: str = "", limit: int = 20) -> str:
            """Read the messages this session exchanged earlier with one other session, or what was said in a group
            chat you are in. The broker keeps them across restarts, so this also shows what was said before either
            session was restarted. You see only your own conversations.

            Args:
                session: The other session: its name or id, from list_sessions or from an earlier message. Give this
                    or group, or neither to see your most recent messages with everyone.
                group: A group chat you are in, such as "review".
                limit: How many of the newest messages to show, 1 to 100 (default 20).

            Snippet:
                message_history(session="fix-parser")
                message_history(group="review", limit=50)

            Guidelines:
                - Use it to recall what you and another session already agreed before you write to them again.
                - Messages are shown oldest first; a long one is cut.
            """
            if session and group:
                raise ValueError("give 'session' or 'group', not both")
            try:
                messages, _ = await messenger.history(with_=session, group=group, limit=max(1, min(limit, 100)))
            except SendError as error:
                raise ValueError(_sentence(error)) from error
            if not messages:
                return "No messages yet."
            me = messenger.client.session.session_id if messenger.client.session is not None else ""
            lines = [f"{len(messages)} message{'s' if len(messages) != 1 else ''}, oldest first:"]
            for item in messages:
                sender = item.get("from", {})
                to = item.get("to", {})
                who = "you" if sender.get("session_id") == me else f"@{sender.get('handle', '?')}"
                if to.get("kind") == "group":
                    where = f"#{to.get('name', '?')}"
                else:
                    where = "you" if to.get("session_id") == me else f"@{to.get('handle', '?')}"
                text = str(item.get("text", ""))
                if len(text) > HISTORY_TEXT:
                    text = f"{text[:HISTORY_TEXT]}... [{len(text)} characters]"
                when = time.strftime("%Y-%m-%d %H:%M", time.localtime(float(item.get("ts", 0))))
                lines.append(f"[{when}] {who} -> {where}: {text}")
            return "\n".join(lines)

        return message_history

    def _group_tool(self) -> AgentTool:
        """Create the tool that makes and changes group chats."""
        messenger = self.messenger

        @tool(name=MANAGE_GROUP_TOOL_NAME)
        async def manage_group(action: str, group: str, members: str = "") -> str:
            """Create or change a group chat of sessions. A message sent to a group (send_message with group=...)
            reaches every other member that is connected. You become a member of a group you create, and only a
            member may write to it or change it.

            Args:
                action: "create" (new group with you and the members), "add" (add members), "remove" (remove members),
                    "leave" (take yourself out), or "delete" (remove the group; what was said stays in the history).
                group: The group's name: letters, digits, '-' or '_', such as "review".
                members: For create, add and remove: session names or ids from list_sessions, separated by commas.

            Snippet:
                manage_group(action="create", group="review", members="fix-parser, docs")
                manage_group(action="leave", group="review")

            Guidelines:
                - Create a group only when your user asked for one, or when several sessions work on one task together.
                - A group with no member left is deleted.
            """
            names = [part.strip() for part in members.split(",") if part.strip()]
            try:
                found = await messenger.manage_group(action, group, names)
            except SendError as error:
                raise ValueError(_sentence(error)) from error
            if found is None:
                return f"Group #{group.lstrip('#').lower()} no longer exists."
            roster = {entry.session_id: entry.handle for entry in messenger.client.roster}
            who = ", ".join(roster.get(m, f"{m[:8]} (offline)") for m in found.members)
            return (
                f"Group #{found.name} has {len(found.members)} member{'s' if len(found.members) != 1 else ''}: {who}."
            )

        return manage_group


__all__ = [
    "LIST_SESSIONS_TOOL_NAME",
    "MANAGE_GROUP_TOOL_NAME",
    "MESSAGE_HISTORY_TOOL_NAME",
    "SEND_MESSAGE_TOOL_NAME",
    "SessionMessagingExtension",
]
