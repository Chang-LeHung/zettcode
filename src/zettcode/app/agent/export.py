"""Render a stored session as a self-contained HTML trace.

The page follows the shape a reader wants when they open a session: a sidebar of
turns on the left, the selected turn's events on the right, each event a card
holding the raw text it carried, the time it was written, and what it cost. The
request the next turn would send is the last entry in the sidebar, so the file
shows both what was said and what the model is carrying now.

The document is one template: nothing is fetched, and every string reaches it
through :func:`html.escape`. The only script is the handful of lines that switch
the sidebar selection, and the page reads fine without it.
"""

from __future__ import annotations

import html
import json
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from string import Template

from zett_agent.messages import AnyMessage, AssistantMessage, SystemMessage, ToolMessage, UserMessage

from .context import ContextReport
from .side import is_side_line
from .storage import MessageLine, Session

#: Characters a block keeps inline before it collapses. The system prompt and
#: long tool output are the only things that usually pass it.
COLLAPSE_AFTER = 220

#: Characters of a turn's opening user line the sidebar shows.
TITLE_CHARS = 64


@dataclass(frozen=True, slots=True)
class Event:
    """One message as the trace shows it.

    Attributes:
        number: ``#N`` position in the whole session, in file order.
        kind: What the message is, which decides its heading and its colour.
        title: Heading the card prints.
        text: Raw text the message carried; markup is escaped, never rendered.
        reasoning: Reasoning that came with an assistant message, if any.
        calls: Tool calls the message asked for, as ``(name, arguments)``.
        ok: Whether a tool result succeeded; ``None`` for other messages.
        created_at: When the message was written.
        duration_ns: Wall time of the call that produced it, when one is known.
        duplicate_of: Number of an earlier event with the same text, so a
            repeated system instruction is pointed at rather than reprinted.
    """

    number: int
    kind: str
    title: str
    text: str
    reasoning: str = ""
    calls: tuple[tuple[str, str], ...] = ()
    ok: bool | None = None
    created_at: datetime | None = None
    duration_ns: int | None = None
    duplicate_of: int | None = None


@dataclass(frozen=True, slots=True)
class Section:
    """One entry in the sidebar and the panel it opens."""

    label: str
    title: str
    stats: str
    note: str = ""
    events: tuple[Event, ...] = field(default=())


@dataclass(frozen=True, slots=True)
class Trace:
    """The whole page: where it came from, and what it holds."""

    title: str
    subtitle: str
    meta: tuple[tuple[str, str], ...]
    sections: tuple[Section, ...]
    tags: tuple[str, ...] = ()
    exported_at: str = ""


def build_trace(
    session: Session,
    *,
    title: str = "",
    subtitle: str = "",
    meta: Sequence[tuple[str, str]] = (),
    tags: Sequence[str] = (),
    context_messages: Sequence[AnyMessage] = (),
    tools: Sequence[str] = (),
    report: ContextReport | None = None,
) -> Trace:
    """Group a stored branch into turns, and put the live context after them."""
    events: list[Event] = []
    seen: dict[str, int] = {}
    for line in session.branch():
        if is_side_line(line):
            # A side question never joined the conversation, so it is not part of
            # the record a reader is handed either.
            continue
        event = _event(len(events) + 1, line)
        if event.text:
            first = seen.setdefault(event.text, event.number)
            if first != event.number:
                event = replace(event, duplicate_of=first)
        events.append(event)
    sections = tuple(_sections(events)) + (_context_section(context_messages, tools, report),)
    stored = session.header.session_id if session.header is not None else "session"
    return Trace(
        title=title or stored,
        subtitle=subtitle,
        meta=tuple(meta),
        sections=tuple(section for section in sections if section.events),
        tags=tuple(tags),
    )


@lru_cache(maxsize=1)
def _assets() -> tuple[Template, str, str]:
    """Read the document, its stylesheet, and its script, once per process.

    They live beside this module as ordinary files — a page is easier to work on
    as markup and CSS than as a Python string — and are folded back into one
    document here, so what is exported still fetches nothing.
    """
    root = files("zettcode.app.agent").joinpath("trace")
    template = Template(root.joinpath("template.html").read_text(encoding="utf-8"))
    style = root.joinpath("style.css").read_text(encoding="utf-8")
    script = root.joinpath("script.js").read_text(encoding="utf-8")
    return template, style, script


def render_html(trace: Trace) -> str:
    """Return the whole page for one trace."""
    template, style, script = _assets()
    return template.substitute(
        style=style,
        script=script,
        title=html.escape(trace.title),
        subtitle=html.escape(trace.subtitle),
        meta=_render_meta(trace.meta),
        tags=_render_tags(trace.tags),
        turns=str(len(trace.sections)),
        summary=html.escape(_summary(trace)),
        sidebar=_render_sidebar(trace.sections),
        panels=_render_panels(trace.sections, _render_tags(trace.tags)),
        exported_at=html.escape(trace.exported_at),
    )


def write_export(path: str | Path, content: str) -> Path:
    """Write the page and return the absolute path that was written."""
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target.resolve()


def _branch_messages(session: Session) -> list[MessageLine]:
    """Return the active branch's message lines, oldest first."""
    return list(session.branch())


def _event(number: int, line: MessageLine) -> Event:
    """Build the event one stored message becomes."""
    message = line.message[0]
    timing = line.timing
    match message:
        case SystemMessage():
            return Event(number, "system", "System instruction", message.content, created_at=line.created_at)
        case UserMessage():
            return Event(number, "user", "User message", message.text, created_at=line.created_at)
        case AssistantMessage():
            calls = tuple(
                (call.name, json.dumps(call.arguments, ensure_ascii=False, sort_keys=True))
                for call in message.tool_calls
            )
            return Event(
                number,
                "assistant",
                "Model response",
                message.content,
                reasoning=message.reasoning or "",
                calls=calls,
                created_at=line.created_at,
                duration_ns=timing.duration_ns,
            )
        case ToolMessage():
            return Event(
                number,
                "tool",
                "Tool result",
                message.text,
                ok=message.success,
                created_at=line.created_at,
                duration_ns=timing.duration_ns,
            )
        case _:
            return Event(number, "other", type(message).__name__, repr(message), created_at=line.created_at)


def _sections(events: Sequence[Event]) -> list[Section]:
    """Split the session's events into turns, one per user message."""
    turns: list[list[Event]] = []
    for event in events:
        if event.kind == "user" or not turns:
            turns.append([])
        turns[-1].append(event)
    sections: list[Section] = []
    for index, turn in enumerate(turns, start=1):
        duration = sum(event.duration_ns or 0 for event in turn) / 1_000_000_000
        opening = next((event for event in turn if event.kind == "user"), turn[0])
        sections.append(
            Section(
                label=f"Turn {index}",
                title=_title(opening.text),
                stats=f"{len(turn)} events · {duration:.1f} s",
                events=tuple(turn),
            )
        )
    return sections


def _context_section(
    messages: Sequence[AnyMessage],
    tools: Sequence[str],
    report: ContextReport | None,
) -> Section:
    """Build the sidebar entry for the request the next turn would send."""
    events: list[Event] = []
    seen: dict[str, int] = {}
    number = 0
    for message in messages:
        number += 1
        event = _context_event(number, message)
        first = seen.setdefault(event.text, event.number) if event.text else event.number
        events.append(replace(event, duplicate_of=first) if first != event.number else event)
    if tools:
        number += 1
        events.append(
            Event(number, "tools", "Tools offered", "\n".join(tools)),
        )
    stats = f"{len(events)} messages"
    note = f"{report.used:,} tokens" if report is not None else ""
    if report is not None:
        stats += f" · {report.used:,} tokens"
    return Section(label="Context", title="Current request", stats=stats, note=note, events=tuple(events))


def _context_event(number: int, message: AnyMessage) -> Event:
    """Build the event one model-facing message becomes."""
    match message:
        case SystemMessage():
            return Event(number, "system", "System instruction", message.content)
        case AssistantMessage():
            calls = tuple(
                (call.name, json.dumps(call.arguments, ensure_ascii=False, sort_keys=True))
                for call in message.tool_calls
            )
            return Event(
                number, "assistant", "Model response", message.content, reasoning=message.reasoning or "", calls=calls
            )
        case ToolMessage():
            return Event(number, "tool", "Tool result", message.text, ok=message.success)
        case UserMessage():
            return Event(number, "user", "User message", message.text)
        case _:
            return Event(number, "other", type(message).__name__, repr(message))


def _title(text: str) -> str:
    """Return the one line a sidebar entry shows for a turn."""
    line = next((part.strip() for part in text.splitlines() if part.strip()), "")
    return line[:TITLE_CHARS] + ("…" if len(line) > TITLE_CHARS else "")


def _summary(trace: Trace) -> str:
    """Return the counts the top bar prints."""
    events = sum(len(section.events) for section in trace.sections)
    return f"{len(trace.sections)} sections · {events} events"


def _render_meta(meta: Sequence[tuple[str, str]]) -> str:
    """Return the sidebar's footer: one small label over each value."""
    return "".join(f"<div><dt>{html.escape(label)}</dt><dd>{html.escape(value)}</dd></div>" for label, value in meta)


def _render_sidebar(sections: Sequence[Section]) -> str:
    """Return the turn buttons, the first one selected."""
    buttons = []
    for index, section in enumerate(sections):
        note = f'<span class="note">{html.escape(section.note)}</span>' if section.note else ""
        current = " is-current" if index == 0 else ""
        buttons.append(
            f'<button class="turn{current}" data-panel="panel-{index}" type="button">'
            f'<span class="turn-top"><span class="label">{html.escape(section.label)}</span>{note}</span>'
            f'<span class="turn-title">{html.escape(section.title)}</span>'
            f'<span class="turn-stats">{html.escape(section.stats)}</span>'
            "</button>"
        )
    return "".join(buttons)


def _render_panels(sections: Sequence[Section], tags: str) -> str:
    """Return one panel per section, the first one selected."""
    panels = []
    for index, section in enumerate(sections):
        current = " is-current" if index == 0 else ""
        panels.append(
            f'<section class="panel{current}" id="panel-{index}">'
            f'<header class="panel-head"><h2>{html.escape(section.label)}</h2>{tags}'
            f'<span class="panel-stats">{html.escape(section.stats)}</span></header>'
            f'<ol class="timeline">{"".join(_render_event(event) for event in section.events)}</ol>'
            "</section>"
        )
    return "".join(panels)


def _render_tags(tags: Sequence[str]) -> str:
    """Return the model and effort chips every panel head carries."""
    return "".join(f'<span class="chip">{html.escape(tag)}</span>' for tag in tags)


def _render_event(event: Event) -> str:
    """Return one event card: heading, metadata, then the text it carried."""
    meta = [f"#{event.number}"]
    if event.created_at is not None:
        meta.append(event.created_at.astimezone().strftime("%H:%M:%S"))
    if event.duration_ns:
        meta.append(f"{event.duration_ns / 1_000_000_000:.2f} s")
    if event.ok is not None:
        meta.append("ok" if event.ok else "failed")
    # A duplicate points at the text instead of repeating it, so it has none to copy.
    copy = (
        ""
        if event.duplicate_of is not None
        else f'<button class="copy" type="button" data-copy="{html.escape(event.text, quote=True)}">Copy</button>'
    )
    return (
        '<li class="event">'
        '<span class="dot"></span>'
        '<div class="event-card">'
        f'<div class="event-head"><h3 class="kind-{html.escape(event.kind)}">{html.escape(event.title)}</h3>{copy}</div>'
        f'<p class="event-meta">{html.escape(" · ".join(meta))}</p>'
        f"{_render_text(event)}"
        f"{_render_reasoning(event)}"
        f"{_render_calls(event)}"
        "</div></li>"
    )


def _render_calls(event: Event) -> str:
    """Return the tool calls an assistant message asked for."""
    if not event.calls:
        return ""
    rows = "".join(
        f'<div class="call"><span class="arrow">→</span>{html.escape(name)}({html.escape(arguments)})</div>'
        for name, arguments in event.calls
    )
    return f'<div class="calls">{rows}</div>'


def _render_text(event: Event) -> str:
    """Return the event's text: inline when short, a collapsible block when long."""
    if not event.text:
        return ""
    if event.duplicate_of is not None:
        return f'<p class="duplicate">Same text as #{event.duplicate_of}.</p>'
    if _is_block(event):
        note = _block_note(event)
        return (
            f'<details class="block"><summary><span class="block-title">{html.escape(event.title)}</span>'
            f'<span class="block-note">{html.escape(note)}</span></summary>'
            f"<pre>{html.escape(event.text)}</pre></details>"
        )
    return f'<div class="body">{_render_inline(event.text)}</div>'


def _render_reasoning(event: Event) -> str:
    """Return the reasoning an assistant message carried, collapsed."""
    if not event.reasoning:
        return ""
    note = f"{len(event.reasoning)} chars"
    return (
        f'<details class="block reasoning"><summary><span class="block-title">Reasoning</span>'
        f'<span class="block-note">{note}</span></summary><pre>{html.escape(event.reasoning)}</pre></details>'
    )


def _is_block(event: Event) -> bool:
    """Return whether the event's text starts collapsed.

    The system prompt is furniture a reader skims past, and a wall of tool
    output hides the rest of the turn; an answer with line breaks in it is what
    the reader came for and stays open.
    """
    return event.kind == "system" or len(event.text) > COLLAPSE_AFTER


def _block_note(event: Event) -> str:
    """Return what a collapsed block shows beside its title."""
    return f"{len(event.text)} chars"


def _render_inline(text: str) -> str:
    """Return short text with its line breaks kept and its markup escaped."""
    return html.escape(text).replace("\n", "<br>")
