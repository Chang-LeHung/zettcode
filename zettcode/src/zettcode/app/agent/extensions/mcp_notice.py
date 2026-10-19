"""What the MCP extension tells the reader, as a custom event the transcript can show.

This is a module of its own, apart from :mod:`.mcp`, because the transcript has to recognise the
event and :mod:`.mcp` imports the MCP SDK, which costs more than the first frame. The name and the
payload live here, where importing them costs nothing.
"""

from __future__ import annotations

from zett_agent.events import AgentEvent

#: Name of the custom event that carries one line of MCP news for the reader.
MCP_NOTICE_EVENT_NAME = "mcp_notice"


#: How serious a line of news is: ``info`` is progress (a server is starting, or ready), ``warn`` is something the
#: reader may need to act on (a server is down, an entry is ignored). A payload that names neither is ``info``.
LEVELS = ("info", "warn")


def notice_payload(text: str, level: str = "info") -> dict[str, str]:
    """Return the JSON-serializable payload that carries one line of MCP news and how serious it is."""
    return {"text": text, "level": level if level in LEVELS else "info"}


def notice_level_from(event: AgentEvent) -> str:
    """Return how serious the notice an event carries is; ``info`` for a payload that does not say."""
    payload = event.payload
    level = payload.get("level") if isinstance(payload, dict) else None
    return level if level in LEVELS else "info"


def notice_from(event: AgentEvent) -> str | None:
    """Return the line an MCP notice event carries, or ``None`` when it carries nothing readable.

    Junk is ignored rather than raised on: an event reaches here from a hook, and a malformed one
    must not be able to fail the request that produced it.
    """
    payload = event.payload
    if event.name != MCP_NOTICE_EVENT_NAME or not isinstance(payload, dict):
        return None
    text = payload.get("text")
    return text.strip() if isinstance(text, str) and text.strip() else None
