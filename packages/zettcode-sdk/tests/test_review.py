"""The review command as the SDK spells it: a preset, its levels, and the name the model chooses."""

from __future__ import annotations

from pathlib import Path

from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.engine.plugins.commands import PlainCommandContext, TurnCommandResult
from zettcode.engine.plugins.context import PluginContext
from zettcode.sdk.review import CodeReview


def _context(tmp_path: Path) -> PluginContext:
    return PluginContext(
        ZettCodeConfig(workspace=tmp_path, models=(ModelConfig(model="m", token="t"),)),
        {},
        name="commandline",
    )


def test_it_registers_one_plain_command_that_queues_behind_a_run(tmp_path: Path):
    ctx = _context(tmp_path)

    CodeReview().register(ctx)

    (command,) = ctx.commands.commands
    assert command.name == "/code-review"
    assert command.when_busy == "queue"
    assert command.summary.startswith("review the uncommitted changes")


def test_a_review_is_a_turn_with_the_focus_the_reader_typed():
    review = CodeReview().review(PlainCommandContext(argument="the parser", level="safe"))

    assert isinstance(review, TurnCommandResult)
    assert review.shown == "/code-review the parser"
    assert review.prompt.startswith("Review the uncommitted changes")
    assert "the parser" in review.prompt and "git diff HEAD" in review.prompt


def test_the_reviewer_is_started_at_the_readers_level_but_never_above_it():
    review = CodeReview()

    assert "spawn --name REVIEW_NAME --permission full" in review.brief(level="full", focus="x")
    assert "spawn --name REVIEW_NAME --permission safe" in review.brief(level="safe", focus="x")
    assert "spawn --name REVIEW_NAME --permission safe" in review.brief(level="ask", focus="x")
    assert "spawn --name <name>" not in review.brief(level="safe", focus="x"), "a shell reads <name> as a redirect"
    assert "REVIEW_NAME" in review.brief(level="safe", focus="x")


def test_under_deny_the_review_is_a_reading_one():
    brief = CodeReview().brief(level="deny", focus="x")

    assert "reading tools" in brief
    assert "spawn" not in brief
