"""The headless ``/hub`` document: who is connected, the daemons, and the messages between sessions."""

from __future__ import annotations

from collections.abc import Mapping

__all__ = ["hub_markdown"]


def _text(value: object, fallback: str = "") -> str:
    return str(value) if value not in (None, "") else fallback


def hub_markdown(snapshot: Mapping[str, object]) -> str:
    """Return the sessions, daemons and message edges as a Markdown document a front end can open."""
    lines = ["# Who is here", ""]
    labels: dict[str, str] = {}
    you = _text(snapshot.get("you"))
    if you:
        labels[you] = "you"
    error = _text(snapshot.get("error"))

    sessions = snapshot.get("sessions") or []
    lines += ["## Sessions", ""]
    if not sessions:
        lines.append("_No session list could be read._" if error else "_No other session is connected._")
    for peer in sessions if isinstance(sessions, (list, tuple)) else ():
        if not isinstance(peer, Mapping):
            continue
        short = _text(peer.get("session_id"), "?")[:8]
        label = _text(peer.get("handle"), short)
        labels[_text(peer.get("session_id"))] = label
        title = _text(peer.get("title"), "untitled")
        status = _text(peer.get("status"), "idle")
        kind = _text(peer.get("kind"), "zettcode")
        lines.append(f"- `{label}` — {title} ({status}, {kind})")

    daemons = snapshot.get("daemons") or []
    lines += ["", "## Daemons", ""]
    if not daemons:
        lines.append("_No daemon is recorded on this machine._")
    for daemon in daemons if isinstance(daemons, (list, tuple)) else ():
        if not isinstance(daemon, Mapping):
            continue
        short = _text(daemon.get("session_id"), "?")[:8]
        label = _text(daemon.get("name") or daemon.get("title"), short)
        labels[_text(daemon.get("session_id"))] = label
        title = _text(daemon.get("title"), "untitled")
        status = _text(daemon.get("status"), "unknown")
        workspace = _text(daemon.get("workspace"))
        where = f", `{workspace}`" if workspace else ""
        lines.append(f"- `{label}` — {title} ({status}{where})")

    lines += ["", "## Messages", ""]
    if error:
        lines.append(f"_{error}_")
    else:
        edges = snapshot.get("edges") or []
        if not edges:
            lines.append("_No messages between sessions yet._")
        for edge in edges if isinstance(edges, (list, tuple)) else ():
            if not isinstance(edge, Mapping):
                continue
            left_id = _text(edge.get("a"))
            right_id = _text(edge.get("b"))
            left = labels.get(left_id, left_id[:8] or "?")
            right = labels.get(right_id, right_id[:8] or "?")
            count = _text(edge.get("count"), "1")
            lines.append(f"- `{left}` ↔ `{right}`: {count} message{'s' if count != '1' else ''}")

    return "\n".join(lines)
