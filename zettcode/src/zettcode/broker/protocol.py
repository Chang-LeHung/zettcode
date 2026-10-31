"""What a ZettCode session and the broker say to each other, and the limits on it.

The broker is a small HTTP server on a loopback port; every route but ``/health`` wants ``Authorization: Bearer
<token>``, the token being in the note a broker leaves for the processes of its owner (see :mod:`.files`).

HTTP, for anyone who holds the token — a session, a script, a hook, ``curl``::

    GET  /sessions     ->  {"sessions": [...], "limits": {...}}
    POST /messages     {"to", "text", "via"?, "hops"?, "mode"?, "from"?: {"name"}}  ->  {"to": {...}, "disposition"}
    GET  /health       ->  {"ok": true}

A failure is an HTTP status and ``{"error": {"reason", "message"}}``; the reason is what a program acts on. A
message's ``mode`` says what a busy recipient should do with it: ``steer`` (the default) hands it to the request
that is running so it changes course, and ``followup`` waits until that request ends. An idle recipient starts a
turn either way.

A *session* — ZettCode's, or any program that wants to be listed and reached — registers by opening a WebSocket at
``/inbox`` and stays registered for as long as it is open. Over it the broker says::

    {"op": "hello", "protocol": 7, "key": ..., "limits": {...}}      first; ``key`` is this connection's credential
    {"op": "roster", "sessions": [...]}                              on arrival and whenever it changes
    {"op": "done", "n": 1, "handle": ...}                            the answer to a session or leave
    {"op": "refused", "n": 1, "error": {"reason", "message"}}        ... or its refusal
    {"op": "deliver", "id": 9, "from": {...}, "text", "hops", "via", "mode"} a message; answer with an ack

and the session says::

    {"op": "session", "n": 1, "session_id", "title", "workspace", "status", "kind"?}   who I am now
    {"op": "leave", "n": 2}                                          I am no one, but stay connected
    {"op": "ack", "id": 9, "accepted": true, "reason": "", "disposition": "started"}  how it took it

A session sends with ``POST /messages`` and ``X-Session-Key: <key>``, which is how the broker knows who the message
is from: the sender's identity is the registration the key belongs to, never something the body says. A request
without a key is from an *external* source, named by ``from.name`` and not listed or replied to. Whoever the
sender, a message carries where it came from (``via``): ``user`` when a reader typed it, ``agent`` when a session's
agent sent it, ``external`` when the sender is not a ZettCode session (it said so itself, and the broker cannot
check it), and a sender that is not a ZettCode session cannot claim to be one of the others.

Compatibility. :data:`PROTOCOL_VERSION` changes whenever anything here changes meaning; a broker speaks one version,
and a session that finds another one ends an older broker or waits for a newer one (see :mod:`.client`). Within a
version a peer ignores fields it does not know. Delivery is *at most once*: a request lost with its connection may
or may not have been carried out, and nothing retries it.

Everything a hostile or merely broken peer could send is bounded here — a message has a length, a name is reduced to
characters the composer can type, a chain of messages that keep triggering one another stops after :data:`MAX_HOPS`
— because both ends read what a local process hands them.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..modes import MODE_STEER, MODES
from .text import clean_text, clean_title

#: Bumped whenever this protocol changes meaning. 7: a message says whether a busy recipient should steer its running
#: request with it or wait behind that request (``mode``, default steer); 6 was the HTTP server and its WebSocket per
#: session, 5 lines of JSON on a TCP socket.
PROTOCOL_VERSION = 7

#: The longest message, in characters. Longer than anyone types, shorter than a paste of a file.
MAX_TEXT = 32_000

#: The longest title the roster keeps; a longer one is cut.
MAX_TITLE = 120

#: The longest workspace path the roster keeps.
MAX_WORKSPACE = 512

#: The longest WebSocket message or request body either end reads, in bytes: a message in the worst case (every
#: character escaped) and a roster of a few hundred sessions both fit. A longer one is refused or ends the connection.
MAX_BODY = 1 << 20

#: How many sessions a message may pass through. A reader who typed it is hop zero; each session whose agent
#: forwards it adds one. Two agents that answer each other would otherwise spend tokens for ever, so the broker
#: refuses the message that would be hop :data:`MAX_HOPS` + 1.
MAX_HOPS = 6

#: Seconds the broker waits for the session a message was handed to to say it took it.
ACK_TIMEOUT = 10.0

#: Messages one connection may send in :data:`RATE_WINDOW` seconds: a runaway agent is a loop of tool calls, and
#: this is the floor it hits before the hop limit does.
RATE_LIMIT = 20
RATE_WINDOW = 60.0

#: A session id as the store writes them (UUIDs), and anything else a test or a plugin invents.
SESSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

#: What a session is doing, as the broker shows it to the others.
STATUSES = ("idle", "working")

#: How a message reached its recipient: a reader typed it into another session, an agent used its tool, or it came
#: from something that is not a ZettCode session at all.
VIA_USER = "user"
VIA_AGENT = "agent"
VIA_EXTERNAL = "external"
VIAS = (VIA_USER, VIA_AGENT, VIA_EXTERNAL)

#: What a sender asks a busy recipient to do with a message — :data:`~zettcode.modes.MODE_STEER` (the default) or
#: :data:`~zettcode.modes.MODE_FOLLOWUP` — is named in :mod:`zettcode.modes`, which every front end may import. The
#: names are imported here only because this is where a mode is checked.

#: What a session can say about a turn that is running, for the sessions that watch it: it began, a piece of the answer,
#: that the model is reasoning, a tool started and ended, it ended. A line is at most :data:`MAX_STREAM` characters.
STREAM_TYPES = ("begin", "text", "thinking", "tool", "tool_end", "end")

#: The most a stream line may weigh as JSON, in characters: pieces are small, and a longer one is dropped, not cut.
MAX_STREAM = 16_000

#: What a registered session is: ZettCode itself, or a program standing in for one.
KIND_ZETTCODE = "zettcode"
KIND_EXTERNAL = "external"
KINDS = (KIND_ZETTCODE, KIND_EXTERNAL)

#: The longest name an external sender may give itself.
MAX_NAME = 40


class Refused(Exception):
    """A request that cannot be done, as a reason a program can act on and a sentence a person can read.

    The reasons: ``invalid``, ``empty``, ``too_long``, ``rate``, ``not_registered``, ``duplicate``, ``unknown``,
    ``ambiguous``, ``self``, ``loop``, ``rejected``, ``gone``, ``timeout``, ``busy``, and ``auth`` for a request
    without the credential.
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason

    def to_wire(self) -> dict[str, str]:
        """Return the ``error`` a line carries."""
        return {"reason": self.reason, "message": str(self)[:300]}

    @classmethod
    def from_wire(cls, raw: object) -> Refused:
        """Read an ``error``; one that is not well formed is still a refusal."""
        if isinstance(raw, Mapping) and isinstance(raw.get("reason"), str) and isinstance(raw.get("message"), str):
            return cls(raw["reason"], raw["message"])
        return cls("invalid", "the other end refused without saying why")


def field(raw: Mapping[str, Any], name: str, kind: type, default: Any = None) -> Any:
    """Return a field of a line, or ``default`` when it is missing; a field of the wrong kind is ``invalid``."""
    value = raw.get(name, default)
    if value is None and default is None:
        raise Refused("invalid", f"{name} is required")
    if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
        raise Refused("invalid", f"{name} must be a {kind.__name__}")
    return value


@dataclass(frozen=True, slots=True)
class PeerInfo:
    """A registered session, as the broker lists it."""

    session_id: str
    handle: str
    title: str
    workspace: str
    status: str
    kind: str = KIND_ZETTCODE
    #: Whether this session runs a message sent with ``direct`` as its reader's own prompt (see :func:`parse_send`).
    direct: bool = False

    def to_wire(self) -> dict[str, str | bool]:
        """Return the entry as it goes over the wire."""
        return {
            "session_id": self.session_id,
            "handle": self.handle,
            "title": self.title,
            "workspace": self.workspace,
            "status": self.status,
            "kind": self.kind,
            "direct": self.direct,
        }

    @classmethod
    def from_wire(cls, raw: object) -> PeerInfo | None:
        """Return the entry a peer described, cleaned, or ``None`` when it is not one.

        Lenient on purpose: this is what a session paints in its menu, so one damaged entry is skipped and the
        rest still show.
        """
        if not isinstance(raw, Mapping):
            return None
        session_id, handle = raw.get("session_id"), raw.get("handle")
        if not isinstance(session_id, str) or not isinstance(handle, str) or not session_id or not handle:
            return None
        return cls(session_id, handle, *_description(raw), _kind(raw), raw.get("direct") is True)


def _description(raw: Mapping[str, Any]) -> tuple[str, str, str]:
    """Return the title, workspace and status of a line, repaired: they describe, so they never refuse."""
    workspace, status = raw.get("workspace"), raw.get("status")
    return (
        clean_title(raw.get("title"), MAX_TITLE),
        clean_text(workspace)[:MAX_WORKSPACE] if isinstance(workspace, str) else "",
        status if isinstance(status, str) and status in STATUSES else "idle",
    )


def _kind(raw: Mapping[str, Any]) -> str:
    kind = raw.get("kind")
    return kind if isinstance(kind, str) and kind in KINDS else KIND_ZETTCODE


def roster_from_wire(raw: object) -> tuple[PeerInfo, ...]:
    """Return the sessions a roster lists, skipping any entry that is not one."""
    if not isinstance(raw, list):
        return ()
    return tuple(entry for entry in (PeerInfo.from_wire(item) for item in raw) if entry is not None)


@dataclass(frozen=True, slots=True)
class Limits:
    """What the broker will accept, told to a session so it can refuse a message before sending it."""

    max_text: int = MAX_TEXT
    max_hops: int = MAX_HOPS
    rate_limit: int = RATE_LIMIT
    rate_window: float = RATE_WINDOW

    def to_wire(self) -> dict[str, Any]:
        """Return the limits as they go over the wire."""
        return {
            "max_text": self.max_text,
            "max_hops": self.max_hops,
            "rate_limit": self.rate_limit,
            "rate_window": self.rate_window,
        }

    @classmethod
    def from_wire(cls, raw: object) -> Limits:
        """Return the limits a broker announced; a missing or odd one keeps this end's own."""
        if not isinstance(raw, Mapping):
            return cls()
        base = cls()

        def number(name: str, fallback: Any) -> Any:
            value = raw.get(name)
            kinds = (int, float) if isinstance(fallback, float) else int
            return value if isinstance(value, kinds) and not isinstance(value, bool) and value > 0 else fallback

        return cls(
            max_text=number("max_text", base.max_text),
            max_hops=number("max_hops", base.max_hops),
            rate_limit=number("rate_limit", base.rate_limit),
            rate_window=float(number("rate_window", base.rate_window)),
        )


@dataclass(frozen=True, slots=True)
class SessionUpdate:
    """What a session says about itself: which it is, what it is called, what it is doing."""

    session_id: str
    title: str = ""
    workspace: str = ""
    status: str = "idle"
    kind: str = KIND_ZETTCODE
    direct: bool = False

    @classmethod
    def parse(cls, raw: Mapping[str, Any]) -> SessionUpdate:
        """Read an ``update``. The id must be one the store could have written; the rest is repaired."""
        session_id = field(raw, "session_id", str)
        if not SESSION_ID.match(session_id):
            raise Refused("invalid", "a session id is 1-64 letters, digits, '.', '_' or '-'")
        return cls(session_id, *_description(raw), _kind(raw), raw.get("direct") is True)


def parse_send(raw: Mapping[str, Any], limits: Limits) -> tuple[str, str, str, int, str]:
    """Read and check a ``send``: who it is for, its cleaned text, how it came, its hops, and its mode.

    The text is cleaned (see :func:`~.text.clean_text`) before it is measured, so the limit is on what would be
    delivered. A message a reader typed, or one from outside, starts a chain whatever hop count it claims. The mode
    is :data:`MODE_STEER` unless the sender asked for :data:`MODE_FOLLOWUP`.

    Raises:
        Refused: ``invalid`` for a field of the wrong kind or a mode the recipient does not know, ``empty`` for
            nothing to say, ``too_long`` past the limit, ``loop`` when the message would pass the hop limit.
    """
    to = field(raw, "to", str)
    text = clean_text(field(raw, "text", str))
    via = field(raw, "via", str, VIA_AGENT)
    hops = field(raw, "hops", int, 0)
    mode = field(raw, "mode", str, MODE_STEER)
    if via not in VIAS:
        raise Refused("invalid", "via is 'user', 'agent' or 'external'")
    if mode not in MODES:
        raise Refused("invalid", "mode is 'steer' or 'followup'")
    if hops < 0:
        raise Refused("invalid", "hops is a count")
    if not text.strip():
        raise Refused("empty", "a message needs some text")
    if len(text) > limits.max_text:
        raise Refused("too_long", f"a message is limited to {limits.max_text} characters")
    hops = 0 if via != VIA_AGENT else hops
    if hops + 1 > limits.max_hops:
        raise Refused("loop", f"this message has already passed through {hops} sessions; not forwarded")
    return to, text, via, hops, mode
