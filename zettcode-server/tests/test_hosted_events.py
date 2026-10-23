"""A hosted tool — a web search — on the wire: the same two frames a local tool has, with its query and pages."""

from __future__ import annotations

from zettcode.sdk.events import ServerToolFinished, ServerToolStarted
from zettcode_server.serialize import event_payload


def test_a_hosted_start_carries_the_name_and_what_it_was_asked():
    payload = event_payload(ServerToolStarted("s1", "call-1", "web_search", {"query": "zettcode github"}))

    assert payload == {
        "type": "server_tool_started",
        "call_id": "call-1",
        "name": "web_search",
        "arguments": {"query": "zettcode github"},
    }


def test_a_hosted_end_carries_the_query_the_pages_and_whether_it_worked():
    payload = event_payload(
        ServerToolFinished(
            "s1",
            "call-1",
            "web_search",
            {"query": "zettcode github"},
            "1 page\n- Page 1 \u2014 https://example.com/1",
            True,
        )
    )

    assert payload == {
        "type": "server_tool_finished",
        "call_id": "call-1",
        "name": "web_search",
        "arguments": {"query": "zettcode github"},
        "output": "1 page\n- Page 1 \u2014 https://example.com/1",
        "ok": True,
    }
