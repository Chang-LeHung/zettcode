"""A stored conversation as a chat: the SDK's messages turned into the items a chat view draws.

The gateway shows a session the way a messenger shows a contact, so a conversation is not a transcript of model
turns but a list of things said (by this gateway, by the session) and a few quiet marks for what the agent did in
between. This module is that translation and nothing else: no I/O, and nothing about HTTP, so every rule here is a
function of the messages it is given.

An item is a plain dict with a ``kind``:

* ``out`` -- this gateway said it (a message the stored conversation records as relayed from the gateway's id);
* ``from`` -- another session or program said it to this one (``sender`` and ``via`` say who);
* ``user`` -- what the person at that session typed, when it is a session with a person at it;
* ``in`` -- what the session's agent answered in words;
* ``reply`` -- the agent used ``send_message`` to speak to this gateway, which is the way a daemon answers;
* ``tool`` -- a tool the agent ran, with a short account of its arguments and how it ended;
* ``note`` -- the summary a compaction left in place of older messages.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Sequence

from zettcode.sdk.types import Message, brief_of

#: The line added after what the reader typed, asking the agent to answer with ``send_message``. A daemon answers a
#: message only when its model chooses to, and a daemon that goes quiet cannot be told from one with nothing to say.
REPLY_REQUEST = (
    '[Web gateway: when you have finished, reply with send_message(to="{id}", message=...). '
    "If there is nothing to report, say so in one line.]"
)

#: Matches the request above whatever id it carries, so the chat shows what the reader typed and not the scaffolding.
_BEFORE, _AFTER = (re.escape(part) for part in REPLY_REQUEST.split("{id}"))
_REPLY_REQUEST = re.compile(rf"\n\n{_BEFORE}[^\"]*{_AFTER}\Z")

#: Longest tool output kept on an item; the chat shows it folded and has no use for more.
OUTPUT_LIMIT = 1_200

#: The tool an agent speaks to another session with.
SEND_TOOL = "send_message"

#: The kinds that are words said to the reader of the chat, as opposed to what the agent did.
SPOKEN = frozenset({"in", "reply"})


def with_reply_request(text: str, gateway_id: str) -> str:
    """Return the text to send: what the reader typed, then the request to answer with ``send_message``."""
    return f"{text}\n\n{REPLY_REQUEST.format(id=gateway_id)}"


def strip_reply_request(text: str) -> str:
    """Return what the reader typed, without the request :func:`with_reply_request` added."""
    return _REPLY_REQUEST.sub("", text)


def items_of(messages: Sequence[Message], gateway_id: str, *, handle: str = "") -> list[dict[str, object]]:
    """Return the chat items for a conversation, oldest first.

    Args:
        messages: The conversation as the SDK reads it.
        gateway_id: The id this gateway is registered under, which marks a message as its own.
        handle: The name the others call this gateway by, which an agent may address a reply to instead of the id.
    """
    results: dict[str, tuple[bool, str]] = {
        message.tool_call_id: (message.ok, message.text)
        for message in messages
        if message.role == "tool" and message.tool_call_id
    }
    ours = {value for value in (gateway_id, handle) if value}
    items: list[dict[str, object]] = []
    for message in messages:
        if message.role == "summary":
            items.append({"kind": "note", "text": message.text})
        elif message.role == "user":
            items.append(_user_item(message, gateway_id))
        elif message.role == "assistant":
            text = message.text.strip()
            if text:
                items.append({"kind": "in", "text": text})
            for call in message.tool_calls:
                items.append(_tool_item(call.id, call.name, call.arguments, results, ours))
    return items


def picture_id(data: bytes) -> str:
    """Return the name a picture is served under: a prefix of its hash, so the same file is the same address."""
    return hashlib.sha256(data).hexdigest()[:20]


def _user_item(message: Message, gateway_id: str) -> dict[str, object]:
    text = strip_reply_request(message.text)
    relay = message.relay
    if relay is None:
        item: dict[str, object] = {"kind": "user", "text": text}
    elif relay.sender_id == gateway_id:
        item = {"kind": "out", "text": text}
    else:
        item = {"kind": "from", "text": text, "sender": relay.sender, "via": relay.via}
    if message.pictures:
        # Named, not inlined: the pictures are fetched one by one and cached, not sent again with every refresh.
        item["images"] = [
            {"id": picture_id(picture.data), "media_type": picture.media_type, "bytes": len(picture.data)}
            for picture in message.pictures
        ]
    return item


def _tool_item(
    call_id: str, name: str, arguments: dict[str, object], results: dict[str, tuple[bool, str]], ours: set[str]
) -> dict[str, object]:
    spoken_to = arguments.get("to")
    said = arguments.get("message")
    if name == SEND_TOOL and isinstance(spoken_to, str) and spoken_to in ours and isinstance(said, str):
        return {"kind": "reply", "text": said.strip()}
    item: dict[str, object] = {"kind": "tool", "name": name, "brief": brief_of(arguments)}
    if call_id in results:
        ok, output = results[call_id]
        item["ok"] = ok
        item["output"] = output if len(output) <= OUTPUT_LIMIT else output[:OUTPUT_LIMIT] + "\n..."
    return item


def spoken(items: Iterable[dict[str, object]]) -> int:
    """Return how many things the session said to this gateway: what a chat counts as unread."""
    return sum(1 for item in items if item["kind"] in SPOKEN)


def preview(items: Sequence[dict[str, object]], limit: int = 90) -> str:
    """Return the line a chat list shows under a name: the last thing said, with ``You:`` before what we said."""
    for item in reversed(items):
        kind = item["kind"]
        if kind not in ("out", "in", "reply", "from", "user"):
            continue
        line = " ".join(str(item["text"]).split())
        if not line:
            continue
        if kind == "out":
            line = f"You: {line}"
        return line if len(line) <= limit else line[: limit - 1] + "\u2026"
    return ""
