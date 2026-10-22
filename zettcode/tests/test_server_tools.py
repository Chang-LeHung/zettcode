"""A search the endpoint ran: one row, with the query, the pages, and no payload.

The call and its result are not messages — the framework reports them as events, and the store keeps them only as the
answer's opaque ``replay_blocks`` — so this is the pair of paths that have to agree: the live event flow, and the walk
of a stored branch after the session is reopened.
"""

from __future__ import annotations

from pathlib import Path

from zett_agent.events import AgentEvent, AgentEventType
from zett_agent.messages import AssistantMessage, UserMessage
from zett_agent.model import ServerToolCall, ServerToolInputDelta, ServerToolResult

from zettcode.app.agent.conversation.projection import TranscriptProjector
from zettcode.app.agent.conversation.replay import replay
from zettcode.app.agent.conversation.server_tools import (
    MAX_RESULTS,
    ServerToolRun,
    describe_output,
    describe_search,
    runs_in_blocks,
)
from zettcode.app.agent.conversation.transcript import Transcript
from zettcode.app.agent.storage import SessionStore

#: One answer as Anthropic records it: the query, ten pages, and the encrypted payloads between them.
BLOCKS = (
    {"type": "thinking", "thinking": "", "signature": "sig"},
    {
        "type": "server_tool_use",
        "id": "call-1",
        "name": "web_search",
        "input": {"query": "zettcode github"},
    },
    {
        "type": "web_search_tool_result",
        "tool_use_id": "call-1",
        "content": [
            {
                "type": "web_search_result",
                "title": f"Page {number}",
                "url": f"https://example.com/{number}",
                "encrypted_content": "SECRET-PAYLOAD",
            }
            for number in range(1, 11)
        ],
    },
    {"type": "text", "text": "Here is the answer."},
)


def _rows(transcript: Transcript) -> list[tuple[str, str, str]]:
    """Return each tool row as ``(tool, title, text)``, the parts a reader recognises."""
    return [
        (entry.tool, entry.title, getattr(entry, "text", ""))
        for entry in transcript.entries
        if getattr(entry, "kind", None) == "tool"
    ]


async def _live(streamed: bool = False) -> Transcript:
    """Run the events one hosted search emits through the projector the shell installs.

    Args:
        streamed: Open the call with no input and send the query in fragments, the way an endpoint may.
    """
    transcript = Transcript()
    projector = TranscriptProjector(transcript)
    projector.begin_turn("search for zettcode")
    opening = None if streamed else {"query": "zettcode github"}
    await projector.dispatch(
        AgentEvent(
            AgentEventType.SERVER_TOOL_STARTED,
            "s",
            server_tool_call=ServerToolCall("call-1", "web_search", opening),
        )
    )
    if streamed:
        for fragment in ('{"quer', 'y": "zett', 'code github"}'):
            await projector.dispatch(
                AgentEvent(
                    AgentEventType.SERVER_TOOL_INPUT_DELTA,
                    "s",
                    server_tool_input_delta=ServerToolInputDelta("call-1", fragment),
                )
            )
    await projector.dispatch(
        AgentEvent(
            AgentEventType.SERVER_TOOL_COMPLETED,
            "s",
            server_tool_result=ServerToolResult("call-1", "web_search", {"content": BLOCKS[2]["content"]}),
        )
    )
    await projector.dispatch(
        AgentEvent(AgentEventType.RUN_COMPLETED, "s", message=AssistantMessage(content="Here is the answer."))
    )
    return transcript


async def _stored(tmp_path: Path) -> Transcript:
    """Store the same answer as the runtime does, then walk the branch the way reopening a session does."""
    store = SessionStore(tmp_path)
    await store.append("s", "req", UserMessage(content="search for zettcode"))
    await store.append(
        "s",
        "req",
        AssistantMessage(
            content="Here is the answer.", provider="anthropic", model="deepseek-flash", replay_blocks=BLOCKS
        ),
    )
    return replay(store.read("s")).transcript


# -- the row -------------------------------------------------------------------------------------------------------


async def test_a_query_that_streams_in_still_reaches_the_row(tmp_path: Path):
    """An endpoint may open the call with no input and send the query in fragments; the row says what was searched."""
    rows = _rows(await _live(streamed=True))

    assert rows[0][1] == 'Searched the web for "zettcode github"'
    assert _rows(await _stored(tmp_path)) == rows, "and a reopened session reads the same"


async def test_live_the_row_says_what_was_searched_for_and_which_pages_came_back():
    rows = _rows(await _live())

    assert len(rows) == 1
    tool, title, text = rows[0]
    assert tool == "web_search" and title == 'Searched the web for "zettcode github"'
    assert text.startswith(f"{MAX_RESULTS + 5} page") and "Page 1 \u2014 https://example.com/1" in text


async def test_replayed_the_same_row_comes_back_from_the_stored_blocks(tmp_path: Path):
    live = await _live()
    again = await _stored(tmp_path)

    assert _rows(again) == _rows(live), "a reopened session shows what the run showed"
    assert not any("SECRET-PAYLOAD" in str(value) for row in _rows(again) for value in row)


async def test_the_pages_are_found_wherever_the_adapter_puts_them():
    """The adapter hands over the block's own ``content``: a bare list, which once read as no results at all."""
    pages = BLOCKS[2]["content"]

    assert describe_search(pages).startswith("10 pages")
    assert describe_search({"content": pages}).startswith("10 pages")
    assert describe_output(ServerToolRun("c", "web_search", {}, output=pages)).startswith("10 pages")


async def test_the_providers_encrypted_payload_is_never_shown():
    text = describe_search({"content": BLOCKS[2]["content"]})

    assert "SECRET-PAYLOAD" not in text and "encrypted" not in text
    assert "Page 2" in text and "https://example.com/2" in text


async def test_a_search_that_found_nothing_says_so_instead_of_an_empty_row():
    assert describe_search({"content": []}) == "No pages"
    assert describe_output(ServerToolRun("c", "web_search", {}, output={"content": []})) == "No pages"


async def test_a_failed_search_shows_the_providers_error_code():
    run = ServerToolRun("c", "web_search", {"query": "x"}, output=None, error="max_uses_exceeded")

    assert describe_output(run) == "max_uses_exceeded"


async def test_blocks_pair_each_result_with_its_call_and_leave_everything_else_alone():
    runs = runs_in_blocks(BLOCKS)

    assert [(run.call_id, run.name, run.arguments["query"]) for run in runs] == [
        ("call-1", "web_search", "zettcode github")
    ]
    assert runs[0].output is not None, "the result block, not only the call"


async def test_a_result_without_its_call_in_the_same_answer_is_left_out():
    assert runs_in_blocks(({"type": "web_search_tool_result", "tool_use_id": "ghost", "content": []},)) == []


async def test_the_window_counts_a_hosted_tool_row():
    from zettcode.app.agent.conversation.replay import entries_added_by

    with_search = AssistantMessage(content="x", replay_blocks=BLOCKS)

    assert entries_added_by(with_search) == entries_added_by(AssistantMessage(content="x")) + 1
