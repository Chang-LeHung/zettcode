"""What a provider-run tool left behind: the rows for a hosted search, live and replayed.

A hosted tool is not called by the agent: the endpoint runs it, and the framework reports the call and its result as
events. Those events are not messages, so the store never sees them; but the provider's own blocks are kept as the
answer's opaque ``replay_blocks``, which the store writes and reads back. This module is the one place that turns
either of those into the words of a row, so a resumed session shows what the live one showed.

The result of a search is a list of pages, each with a title, a URL and an opaque encrypted payload that must never be
put in front of the reader or sent back in a prompt as text: only the title and the URL are shown here.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

#: The most pages one row lists. A row is a note that a search happened, not the search's own page.
MAX_RESULTS = 5

#: Result blocks whose payload is the provider's own and is never shown as text.
_SEARCH_RESULT_TYPES = frozenset({"web_search_result", "search_result"})

#: Block types that record a hosted call rather than text.
_CALL_TYPES = frozenset({"server_tool_use"})


@dataclass(frozen=True, slots=True)
class ServerToolRun:
    """One hosted tool call as the transcript needs it.

    Attributes:
        call_id: The provider's identifier for the call.
        name: The tool's name, such as ``web_search``.
        arguments: What it was asked, when the provider said; ``{"query": ...}`` for a search.
        output: What it returned, as the provider reported it.
        error: The provider's error code when the tool failed.
    """

    call_id: str
    name: str
    arguments: Mapping[str, Any]
    output: Any = None
    error: str | None = None


def _results_in(output: Any) -> list[Mapping[str, Any]]:
    """Return the page blocks of a search result, wherever the provider put them.

    The adapter hands a hosted tool's output over as the block's own ``content``: a list of pages for a search, with
    the provider's encrypted payload beside each title and URL.
    """
    match output:
        case bool() | str() | int() | float() | None:
            return []
        case Mapping():
            content = output.get("content")
            if isinstance(content, Iterable) and not isinstance(content, str):
                return [item for item in content if isinstance(item, Mapping)]
            if output.get("type") in _SEARCH_RESULT_TYPES:
                return [output]
            return []
        case Iterable():
            return [item for item in output if isinstance(item, Mapping)]
        case _:
            return []


def describe_search(output: Any) -> str:
    """Return a search result as the few lines a row shows: how many pages, and which.

    Only a page's title and URL are shown; the encrypted payload the provider returns beside them is its own business
    and is neither printed nor kept.
    """
    pages = _results_in(output)
    if not pages:
        return "No pages"
    lines = [f"{len(pages)} page{'s' if len(pages) != 1 else ''}"]
    for page in pages[:MAX_RESULTS]:
        title = page.get("title")
        url = page.get("url")
        named = title.strip() if isinstance(title, str) and title.strip() else ""
        address = url.strip() if isinstance(url, str) and url.strip() else ""
        lines.append(f"- {named} \u2014 {address}" if named and address else f"- {named or address}")
    if len(pages) > MAX_RESULTS:
        lines.append(f"\u2026 and {len(pages) - MAX_RESULTS} more")
    return "\n".join(lines)


def describe_output(run: ServerToolRun) -> str:
    """Return what one hosted tool said, in the words of its own kind."""
    if run.error:
        return run.error
    if run.name == "web_search" or _results_in(run.output):
        return describe_search(run.output)
    # Another provider's hosted tool: its payload is already text or a plain structure.
    return run.output if isinstance(run.output, str) else ""


def runs_in_blocks(blocks: Iterable[Mapping[str, Any]]) -> list[ServerToolRun]:
    """Return the hosted tool calls one answer's ``replay_blocks`` record, results paired with their calls.

    A block that is not a hosted call is skipped: a thinking block, or the answer's text. A call whose result is not
    in the same answer keeps an empty output, which reads as a search that said nothing.
    """
    calls: dict[str, ServerToolRun] = {}
    order: list[str] = []
    for block in blocks:
        match block.get("type"):
            case "server_tool_use":
                call_id = block.get("id")
                name = block.get("name")
                if not isinstance(call_id, str) or not isinstance(name, str):
                    continue
                call_input = block.get("input")
                arguments = dict(call_input) if isinstance(call_input, Mapping) else {}
                calls[call_id] = ServerToolRun(call_id, name, arguments)
                order.append(call_id)
            case "web_search_tool_result" | "server_tool_result" | "web_fetch_tool_result":
                found = block.get("tool_use_id") or block.get("call_id")
                if not isinstance(found, str) or found not in calls:
                    continue
                error = block.get("error_code")
                calls[found] = ServerToolRun(
                    found,
                    calls[found].name,
                    calls[found].arguments,
                    output=block,
                    error=str(error) if isinstance(error, str) and error else None,
                )
    return [calls[call_id] for call_id in order]


def answer_after_tools(blocks: Iterable[Mapping[str, Any]]) -> bool:
    """Return whether the answer's text came after its hosted tool, as the provider streamed them.

    Anthropic runs a hosted search before it writes the answer, so the row belongs above it; a provider that writes
    first and searches after (DeepSeek does, when it announces the search) has it below. The blocks record which.
    """
    first_tool: int | None = None
    for index, block in enumerate(blocks):
        kind = block.get("type")
        if first_tool is None and kind in _CALL_TYPES:
            first_tool = index
        elif kind == "text" and isinstance(block.get("text"), str) and block["text"].strip():
            return first_tool is not None
    return False


__all__ = [
    "MAX_RESULTS",
    "ServerToolRun",
    "answer_after_tools",
    "describe_output",
    "describe_search",
    "runs_in_blocks",
]
