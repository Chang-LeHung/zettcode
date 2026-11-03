"""The line a request ends on: its items, their switches, a plugin's own item, and how the row packs them."""

from __future__ import annotations

import pytest

from zettcode.app import Transcript, TranscriptView
from zettcode.app.agent.conversation.text import (
    cache_text,
    calls_text,
    pack_segments,
    speed_text,
    tokens_text,
    tools_text,
)
from zettcode.app.plugins.builtins import BUILTIN_PLUGINS
from zettcode.app.plugins.loader import terminal_context
from zettcode.app.plugins.state import TurnContext
from zettcode.app.ui.turns import TurnTally, turn_parts
from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.sdk.events import ToolFinished, ToolStarted
from zettcode.sdk.types import Usage
from zettcode.statusline import NAMES, TURN_PARTS, is_part, unknown
from zettcode.tui import DARK
from zettcode.tui.testing.snapshot import render_block

SESSION = "s"
FULL = "Processed for 12s · 22:53 · ↑12.3k ↓1.2k · 87.0% cached · 3 model calls · 62 tok/s · 5 tool calls, 1 failed"


def spent_usage(**changes) -> Usage:
    base = {"input_tokens": 12_345, "output_tokens": 1_234, "cache_read_tokens": 10_740, "seconds": 20.0, "requests": 3}
    return Usage(**{**base, **changes})


def context(usage: Usage | None = None, tools: int = 5, failed: int = 1) -> TurnContext:
    return TurnContext("Processed", 12.0, "22:53", usage or spent_usage(), tools, failed)


def builtin_segments(tmp_path):
    """The items the program registers, as the shell receives them."""
    ctx = terminal_context(ZettCodeConfig(workspace=tmp_path, models=(ModelConfig(model="m", token="t"),)))
    for plugin in BUILTIN_PLUGINS:
        if plugin.name == "turn-line":
            plugin.activate(ctx)
    return ctx, ctx.tui.turn_segments


def view(parts: tuple[str, ...], width: int, height: int = 10) -> str:
    transcript = Transcript(clock=lambda: 0.0)
    transcript.begin_turn("go")
    transcript.settle_wait("Processed for 12s · 22:53", parts)
    return render_block(TranscriptView(transcript, theme=DARK), width=width, height=height, theme=DARK)


def rows_of(frame: str) -> list[str]:
    return [row for row in frame.split("-- styles --")[0].splitlines() if row.strip()]


# -- the facts -----------------------------------------------------------------------------------------------------
def test_each_fact_says_what_the_vscode_receipt_says_in_the_same_conditions():
    usage = spent_usage()

    assert tokens_text(usage) == "↑12.3k ↓1.2k"
    assert cache_text(usage) == "87.0% cached"
    assert calls_text(usage) == "3 model calls"
    assert speed_text(usage) == "62 tok/s"
    assert tools_text(5, 1) == "5 tool calls, 1 failed"


def test_a_fact_with_nothing_to_say_is_none():
    quiet = spent_usage(requests=1, cache_read_tokens=0, seconds=0.0)

    assert (cache_text(quiet), calls_text(quiet), speed_text(quiet), tools_text(0)) == (None, None, None, None)
    assert tokens_text(Usage()) is None, "nothing before the model has answered"


def test_the_speed_is_given_to_a_tenth_below_ten_and_whole_above_and_not_at_all_below_one():
    assert speed_text(spent_usage(output_tokens=100)) == "5.0 tok/s"
    assert speed_text(spent_usage(output_tokens=10)) is None


def test_one_tool_call_is_singular():
    assert tools_text(1) == "1 tool call" and tools_text(2) == "2 tool calls"


# -- the items -----------------------------------------------------------------------------------------------------
def test_the_program_registers_one_item_for_each_name_it_lists_and_in_that_order(tmp_path):
    _, segments = builtin_segments(tmp_path)

    assert [segment.name for segment in segments] == [name for name, _ in TURN_PARTS]
    assert all(name in NAMES for name, _ in TURN_PARTS), "so the config and /statusline accept every one"


def test_the_items_make_the_line_in_order(tmp_path):
    _, segments = builtin_segments(tmp_path)

    assert " · ".join(turn_parts(segments, context(), ())) == FULL


def test_an_item_that_is_switched_off_is_left_out_and_the_rest_close_up(tmp_path):
    _, segments = builtin_segments(tmp_path)

    parts = turn_parts(segments, context(), {"turn-clock", "turn-speed"})

    assert (
        " · ".join(parts) == "Processed for 12s · ↑12.3k ↓1.2k · 87.0% cached · 3 model calls · 5 tool calls, 1 failed"
    )


def test_a_plugin_adds_an_item_and_it_is_a_switch_like_the_others(tmp_path):
    ctx, _ = builtin_segments(tmp_path)
    ctx.tui.register_turn_segment("turn-branch", "The branch", lambda turn: "main")
    segments = ctx.tui.turn_segments

    assert turn_parts(segments, context(), ())[-1] == "main"
    assert "main" not in turn_parts(segments, context(), {"turn-branch"})
    assert is_part("turn-branch") and unknown(["turn-branch", "nope"]) == ["nope"]


def test_a_plugin_replaces_an_item_by_its_name_where_it_stands(tmp_path):
    ctx, _ = builtin_segments(tmp_path)
    ctx.tui.register_turn_segment("turn-clock", "The clock", lambda turn: f"at {turn.clock}")

    parts = turn_parts(ctx.tui.turn_segments, context(), ())

    assert parts[1] == "at 22:53" and len(parts) == len(TURN_PARTS)


def test_an_item_that_raises_or_says_nothing_costs_only_itself(tmp_path):
    ctx, _ = builtin_segments(tmp_path)

    def broken(turn):
        raise RuntimeError("no")

    ctx.tui.register_turn_segment("turn-broken", "Fails", broken)
    ctx.tui.register_turn_segment("turn-empty", "Silent", lambda turn: None)

    assert " · ".join(turn_parts(ctx.tui.turn_segments, context(), ())) == FULL


def test_an_item_is_named_with_the_prefix(tmp_path):
    ctx, _ = builtin_segments(tmp_path)

    with pytest.raises(ValueError, match="turn-"):
        ctx.tui.register_turn_segment("branch", "no prefix", lambda turn: "x")
    with pytest.raises(ValueError):
        ctx.tui.register_turn_segment("turn-", "nothing after it", lambda turn: "x")


# -- the packing and the row ---------------------------------------------------------------------------------------
def test_segments_share_a_row_while_they_fit_and_break_between_two_and_never_inside_one():
    segments = ["Processed for 12s", "22:53", "↑12.3k ↓1.2k", "87.0% cached", "3 model calls"]

    assert pack_segments(segments, 80) == ["Processed for 12s · 22:53 · ↑12.3k ↓1.2k · 87.0% cached · 3 model calls"]
    assert pack_segments(segments, 30) == ["Processed for 12s · 22:53", "↑12.3k ↓1.2k · 87.0% cached", "3 model calls"]


def test_a_segment_wider_than_the_room_is_cut_so_no_row_is_too_wide():
    rows = pack_segments(["a" * 50], 10)

    assert len(rows) == 1 and len(rows[0]) <= 10


def test_the_settled_row_draws_its_items_on_one_line_when_they_fit():
    assert f"  {FULL}" in rows_of(view(tuple(FULL.split(" · ", 5)[:0]) or tuple(FULL.split(" · ")), width=120))


def test_a_narrow_terminal_gets_further_rows_each_indented_and_never_cut_through():
    rows = rows_of(view(tuple(FULL.split(" · ")), width=40))
    tail = rows[rows.index("  Processed for 12s · 22:53") :]

    assert "  ↑12.3k ↓1.2k · 87.0% cached" in tail
    assert all(row.startswith("  ") and len(row) <= 40 for row in tail)
    assert any("5 tool calls, 1 failed" in row for row in tail), "the failures stay with the calls"


def test_a_row_given_no_items_is_what_it_always_was():
    rows = rows_of(view((), width=44))

    assert rows[-1] == "  Processed for 12s · 22:53" and not any("↑" in row for row in rows)


# -- the tally -----------------------------------------------------------------------------------------------------
def test_the_tally_is_the_usage_after_less_the_usage_before_and_counts_tools_from_the_events():
    tally = TurnTally(Usage(input_tokens=1_000, output_tokens=100, requests=2, seconds=4.0))

    tally.see(ToolStarted(SESSION, "a", "bash", {}))
    tally.see(ToolFinished(SESSION, "a", "bash", "ok", True))
    tally.see(ToolStarted(SESSION, "b", "bash", {}))
    tally.see(ToolFinished(SESSION, "b", "bash", "boom", False))
    tally.see(ToolStarted(SESSION, "c", "ask", {}))
    tally.see(ToolFinished(SESSION, "c", "ask", "declined", False, True))
    turn = tally.context(
        Usage(input_tokens=1_500, output_tokens=300, requests=4, seconds=10.0),
        label="Processed",
        seconds=7.0,
        clock="22:53",
    )

    assert (turn.usage.input_tokens, turn.usage.output_tokens, turn.usage.requests) == (500, 200, 2)
    assert turn.tools == 3 and turn.failed_tools == 1, "a skipped question is not a failure"
    assert turn.label == "Processed" and turn.seconds == 7.0
