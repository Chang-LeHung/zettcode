"""The state file: what survives a restart, and what a damaged one costs."""

from __future__ import annotations

import json
import stat
from pathlib import Path

from zettcode.im.state import CHATS_LIMIT, SEEN_LIMIT, BridgeState


def test_a_saved_state_reads_back_with_everything_a_restart_needs(tmp_path: Path) -> None:
    state = BridgeState.load(tmp_path / "state.json")
    state.handshake = {"qr_content": "https://example.com/qr", "state": {"qrcode": "abc"}}
    state.credentials = {"bot_token": "secret-token"}
    state.session_id = "01a1"
    state.remember("event-1", cursor="cur-1", chat_id="chat-1", reply_token="token-1")
    state.workspace = "/w"
    state.model = "m"
    state.effort = "high"
    state.permission = "deny"
    state.allow = ["u1"]
    state.save()

    again = BridgeState.load(tmp_path / "state.json")

    assert again.handshake["state"] == {"qrcode": "abc"}
    assert again.token() == "secret-token" and again.logged_in
    assert again.cursor == "cur-1" and again.session_id == "01a1"
    assert again.reply_token("chat-1") == "token-1"
    assert (again.workspace, again.model, again.effort, again.permission) == ("/w", "m", "high", "deny")
    assert again.allow == ["u1"] and again.answered("event-1")


def test_the_state_file_is_readable_by_this_user_only(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    state = BridgeState.load(path)
    state.credentials = {"bot_token": "secret"}
    state.save()

    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600, f"a token sits in this file, and it is {mode:o}"


def test_a_missing_or_broken_file_is_a_first_run_and_not_a_crash(tmp_path: Path) -> None:
    assert not BridgeState.load(tmp_path / "state.json").logged_in

    (tmp_path / "state.json").write_text("not json at all", encoding="utf-8")
    assert not BridgeState.load(tmp_path / "state.json").logged_in

    (tmp_path / "state.json").write_text(json.dumps({"credentials": "a string", "seen": "no"}), encoding="utf-8")
    state = BridgeState.load(tmp_path / "state.json")
    assert state.credentials == {} and state.seen == []


def test_an_answer_moves_the_cursor_and_the_remembered_ids_stay_bounded(tmp_path: Path) -> None:
    state = BridgeState.load(tmp_path / "state.json")
    for index in range(SEEN_LIMIT + 5):
        state.remember(f"event-{index}", cursor=f"cur-{index}", chat_id="chat", reply_token="token")

    assert state.cursor == f"cur-{SEEN_LIMIT + 4}", "the newest message is where the next poll starts"
    assert len(state.seen) == SEEN_LIMIT, "the oldest ids fall out rather than growing for ever"
    assert not state.answered("event-0") and state.answered(f"event-{SEEN_LIMIT + 4}")


def test_only_the_newest_chats_keep_a_reply_context(tmp_path: Path) -> None:
    state = BridgeState.load(tmp_path / "state.json")
    for index in range(CHATS_LIMIT + 3):
        state.remember(f"e{index}", cursor="c", chat_id=f"chat-{index}", reply_token=f"t{index}")

    assert len(state.chats) == CHATS_LIMIT
    assert state.reply_token("chat-0") is None and state.reply_token(f"chat-{CHATS_LIMIT + 2}") == f"t{CHATS_LIMIT + 2}"


def test_a_message_without_a_context_token_forgets_the_one_that_chat_had(tmp_path: Path) -> None:
    """The platform's context belongs to one message; carrying it past a message without one would quote the wrong."""
    state = BridgeState.load(tmp_path / "state.json")
    state.remember("e1", cursor="c1", chat_id="chat", reply_token="old")
    state.remember("e2", cursor="c2", chat_id="chat", reply_token=None)

    assert state.reply_token("chat") is None


def test_the_token_is_read_from_where_the_im_client_puts_it(tmp_path: Path) -> None:
    """`agim` hands back `{"config": …, "secrets": {"bot_token": …}}`; a token read from the top level is empty."""
    state = BridgeState.load(tmp_path / "state.json")
    state.credentials = {"config": {"base_url": "https://example.com"}, "secrets": {"bot_token": "secret-token"}}

    assert state.token() == "secret-token" and state.logged_in

    state.credentials = {"config": {}}
    assert state.token() == "" and not state.logged_in, "a login without a token is not a login"
