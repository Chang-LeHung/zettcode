"""The gateway's chat items: a stored conversation read as things said, and the request that asks for an answer."""

from __future__ import annotations

from zettcode.gateway.chat import (
    OUTPUT_LIMIT,
    items_of,
    preview,
    spoken,
    strip_reply_request,
    with_reply_request,
)
from zettcode.sdk.types import Message, Relay, ToolCallInfo

GATEWAY = "01gateway"


def relayed(text: str, *, sender: str = GATEWAY, via: str = "user") -> Message:
    return Message("user", text, relay=Relay(sender, "web-gateway" if sender == GATEWAY else "peer", via, 1))


def test_the_request_for_an_answer_is_added_and_taken_off_again_whatever_id_it_carries():
    sent = with_reply_request("check the build", GATEWAY)

    assert sent.startswith("check the build\n\n") and GATEWAY in sent and "send_message" in sent
    assert strip_reply_request(sent) == "check the build"
    assert strip_reply_request(with_reply_request("x", "some-other-id-7")) == "x"


def test_only_the_request_at_the_very_end_is_taken_off():
    quoted = 'he wrote "[Web gateway: when you have finished, reply with send_message(to="x", message=...)." in a file'

    assert strip_reply_request(quoted) == quoted
    assert strip_reply_request("plain") == "plain"


def test_what_the_gateway_said_is_ours_and_what_another_session_said_is_from_it():
    items = items_of(
        [
            relayed(with_reply_request("look at the diff", GATEWAY)),
            relayed("can you help?", sender="01peer", via="agent"),
            Message("user", "typed at the terminal"),
        ],
        GATEWAY,
    )

    assert items == [
        {"kind": "out", "text": "look at the diff"},
        {"kind": "from", "text": "can you help?", "sender": "peer", "via": "agent"},
        {"kind": "user", "text": "typed at the terminal"},
    ]


def test_an_answer_in_words_is_in_and_send_message_to_us_is_a_reply_not_a_tool():
    to_us = ToolCallInfo("c1", "send_message", {"to": GATEWAY, "message": "  all green  "})
    to_handle = ToolCallInfo("c2", "send_message", {"to": "web-gateway", "message": "by name"})
    elsewhere = ToolCallInfo("c3", "send_message", {"to": "01other", "message": "not for us"})

    items = items_of(
        [
            Message("assistant", "I will look.", tool_calls=(to_us, to_handle, elsewhere)),
            Message("tool", "Delivered", tool_call_id="c3", tool_name="send_message"),
        ],
        GATEWAY,
        handle="web-gateway",
    )

    assert [item["kind"] for item in items] == ["in", "reply", "reply", "tool"]
    assert items[1]["text"] == "all green" and items[2]["text"] == "by name"
    assert items[3] == {"kind": "tool", "name": "send_message", "brief": "01other", "ok": True, "output": "Delivered"}


def test_a_tool_is_one_line_with_how_it_ended_and_a_long_output_is_cut():
    call = ToolCallInfo("c1", "bash", {"command": "pytest   -x\n  tests/"})
    pending = ToolCallInfo("c2", "read", {"path": "src/a.py"})
    long = "x" * (OUTPUT_LIMIT + 50)

    items = items_of(
        [
            Message("assistant", "", tool_calls=(call, pending)),
            Message("tool", long, tool_call_id="c1", tool_name="bash", ok=False),
        ],
        GATEWAY,
    )

    assert items[0]["brief"] == "pytest -x tests/" and items[0]["ok"] is False
    assert str(items[0]["output"]).endswith("\n...") and len(str(items[0]["output"])) == OUTPUT_LIMIT + 4
    assert items[1] == {"kind": "tool", "name": "read", "brief": "src/a.py"}, "a call with no result yet has no ok"


def test_an_assistant_message_with_no_words_and_no_tools_says_nothing():
    assert items_of([Message("assistant", "   ")], GATEWAY) == []


def test_a_compaction_summary_is_a_note():
    assert items_of([Message("summary", "earlier: fixed the parser")], GATEWAY) == [
        {"kind": "note", "text": "earlier: fixed the parser"}
    ]


def test_unread_counts_what_the_session_said_to_us_and_not_what_it_did():
    items = [
        {"kind": "out", "text": "a"},
        {"kind": "in", "text": "b"},
        {"kind": "tool", "name": "x", "brief": ""},
        {"kind": "reply", "text": "c"},
        {"kind": "note", "text": "d"},
    ]

    assert spoken(items) == 2


def test_the_preview_is_the_last_thing_said_with_you_before_ours_and_is_cut_to_a_line():
    assert preview([{"kind": "in", "text": "first"}, {"kind": "out", "text": "second\n  line"}]) == "You: second line"
    assert preview([{"kind": "out", "text": "q"}, {"kind": "tool", "name": "x", "brief": ""}]) == "You: q"
    assert preview([{"kind": "tool", "name": "x", "brief": ""}, {"kind": "note", "text": "n"}]) == ""
    assert preview([{"kind": "in", "text": "w" * 200}], limit=10) == "w" * 9 + "\u2026"
    assert preview([]) == ""
