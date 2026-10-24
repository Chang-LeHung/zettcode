"""The plain values the SDK returns: arithmetic, validation, and that nothing about them is shared or mutable."""

from __future__ import annotations

import dataclasses
from datetime import datetime

import pytest

from zettcode.sdk.types import (
    Compaction,
    ContextReport,
    ContextShare,
    Image,
    Message,
    ModelInfo,
    RunResult,
    SessionInfo,
    ToolRecord,
    Usage,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 8


# -- Usage ----------------------------------------------------------------------------------------


def test_usage_totals_input_and_output_without_counting_cache_or_reasoning_twice():
    usage = Usage(input_tokens=100, output_tokens=40, cache_read_tokens=60, reasoning_tokens=25)

    assert usage.total_tokens == 140


def test_the_cache_hit_rate_is_none_before_any_input_and_a_fraction_after():
    assert Usage().cache_hit_rate is None
    assert Usage(input_tokens=200, cache_read_tokens=50).cache_hit_rate == 0.25
    assert Usage(input_tokens=10, cache_read_tokens=10).cache_hit_rate == 1.0


def test_the_output_rate_needs_measured_time():
    assert Usage(output_tokens=100).output_rate is None
    assert Usage(output_tokens=100, seconds=0.0).output_rate is None
    assert Usage(output_tokens=100, seconds=4.0).output_rate == 25.0


def test_since_subtracts_the_counters_and_keeps_the_level_of_the_context():
    before = Usage(input_tokens=100, output_tokens=10, requests=1, seconds=1.0, context_tokens=90)
    after = Usage(input_tokens=250, output_tokens=40, requests=3, seconds=2.5, context_tokens=210)

    spent = after.since(before)

    assert (spent.input_tokens, spent.output_tokens, spent.requests) == (150, 30, 2)
    assert spent.seconds == pytest.approx(1.5)
    assert spent.context_tokens == 210, "a level is not a counter, so it is what it is now"


def test_since_never_goes_below_zero_when_a_counter_went_backwards():
    """A session switched or replayed between two readings can make a total smaller; a negative spend is never true."""
    spent = Usage(input_tokens=10, seconds=1.0, requests=1).since(Usage(input_tokens=500, seconds=9.0, requests=7))

    assert (spent.input_tokens, spent.requests, spent.seconds) == (0, 0, 0.0)


def test_since_an_equal_reading_spends_nothing():
    reading = Usage(input_tokens=5, output_tokens=5, requests=1, seconds=0.5, context_tokens=7)

    spent = reading.since(reading)

    assert spent.total_tokens == 0 and spent.requests == 0 and spent.seconds == 0.0


def test_usage_is_immutable_and_hashable():
    usage = Usage(input_tokens=1)

    with pytest.raises(dataclasses.FrozenInstanceError):
        usage.input_tokens = 2  # type: ignore[misc]
    assert {usage: 1}[Usage(input_tokens=1)] == 1


# -- Image ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("media_type", ["image/png", "image/jpeg", "image/gif", "image/webp"])
def test_the_four_media_types_a_model_takes_are_accepted(media_type):
    assert Image(PNG, media_type).media_type == media_type


@pytest.mark.parametrize("media_type", ["", "image/svg+xml", "image/PNG", "application/pdf", "text/plain", "png"])
def test_any_other_media_type_is_refused_here_and_not_by_the_provider(media_type):
    with pytest.raises(ValueError, match="Unsupported image type"):
        Image(PNG, media_type)


@pytest.mark.parametrize("data", [b"", bytearray()])
def test_an_image_needs_bytes(data):
    with pytest.raises(ValueError, match="encoded bytes"):
        Image(data, "image/png")


@pytest.mark.parametrize("data", ["text", None, 5, [1, 2]])
def test_an_image_is_bytes_and_nothing_that_looks_like_it(data):
    with pytest.raises(ValueError, match="encoded bytes"):
        Image(data, "image/png")  # type: ignore[arg-type]


def test_an_image_can_be_read_from_a_file_by_its_extension(tmp_path):
    for name, media_type in (
        ("a.png", "image/png"),
        ("b.jpg", "image/jpeg"),
        ("c.JPEG", "image/jpeg"),
        ("d.gif", "image/gif"),
    ):
        (tmp_path / name).write_bytes(PNG)

        assert Image.from_path(tmp_path / name).media_type == media_type


def test_an_image_file_with_an_unknown_extension_or_no_content_is_refused(tmp_path):
    (tmp_path / "notes.txt").write_bytes(PNG)
    (tmp_path / "blank.png").write_bytes(b"")
    (tmp_path / "noextension").write_bytes(PNG)

    for name in ("notes.txt", "blank.png", "noextension"):
        with pytest.raises(ValueError):
            Image.from_path(tmp_path / name)


def test_a_missing_image_file_is_an_os_error_not_a_value_error(tmp_path):
    with pytest.raises(OSError):
        Image.from_path(tmp_path / "gone.png")


def test_an_image_path_may_be_text():
    with pytest.raises(OSError):
        Image.from_path("/definitely/not/here.png")


# -- RunResult ------------------------------------------------------------------------------------


def test_a_result_is_ok_until_the_model_stops_for_a_reason():
    assert RunResult("done", "s").ok
    assert not RunResult("", "s", stop="refusal").ok


def test_the_failed_tools_of_a_result_are_the_ones_that_did_not_succeed():
    good = ToolRecord("1", "read_file", {}, "text", ok=True)
    bad = ToolRecord("2", "bash", {"command": "x"}, "boom", ok=False)
    skipped = ToolRecord("3", "bash", {}, "", ok=False, skipped=True)

    result = RunResult("done", "s", tools=(good, bad, skipped))

    assert result.failed_tools == (bad, skipped)


def test_a_result_with_nothing_in_it_has_defaults_that_are_empty_not_none():
    result = RunResult("", "s")

    assert result.tools == () and result.questions == () and result.events == ()
    assert result.usage == Usage() and result.stop is None


# -- the rest -------------------------------------------------------------------------------------


def test_the_context_report_never_reports_a_negative_free_space_or_divides_by_zero():
    assert ContextReport(window=1000, used=250, measured_by="t").free == 750
    assert ContextReport(window=1000, used=1500, measured_by="t").free == 0
    assert ContextReport(window=1000, used=250, measured_by="t").fraction == 0.25
    assert ContextReport(window=0, used=10, measured_by="t").fraction == 0.0


def test_the_context_report_divides_the_window_by_the_provider_and_the_rows_by_the_tokenizer():
    shares = (ContextShare("System prompt", 300), ContextShare("Tool output", 700))
    report = ContextReport(window=2000, used=2500, measured_by="tiktoken", shares=shares, from_provider=True)

    assert report.measured == 1000, "what the tokenizer counted, while used is the provider's"
    assert report.percent(500) == 25.0, "of the window"
    assert report.share(700) == 70.0, "of what was measured, so the rows add to a hundred"
    assert sum(report.share(s.tokens) for s in shares) == 100.0
    empty = ContextReport(window=0, used=0, measured_by="t")
    assert (empty.measured, empty.percent(5), empty.share(5)) == (0, 0.0, 0.0)


def test_a_report_is_an_estimate_when_it_says_it_counted_characters():
    assert ContextReport(window=1, used=0, measured_by="~4 chars/token").estimated
    assert not ContextReport(window=1, used=0, measured_by="tiktoken cl100k_base").estimated


def test_the_sdks_report_agrees_with_the_engines_on_every_figure_a_page_reads():
    """The terminal draws the SDK's report; the engine's is what it used to draw. They must not drift."""
    from zettcode.engine.extensions import context as engine

    rows = (engine.ContextShare("Tool schemas", 1520, 9), engine.ContextShare("Tool output", 20216, 17))
    for label in ("tiktoken cl100k_base", "~4 chars/token"):
        for reported in (None, 30_000):
            theirs = engine.ContextReport(
                window=200_000, measured_by=label, shares=rows, partial=True, reported=reported
            )
            ours = ContextReport(
                window=200_000,
                used=theirs.used,
                measured_by=label,
                shares=tuple(ContextShare(s.name, s.tokens, s.items) for s in rows),
                partial=True,
                from_provider=theirs.from_provider,
            )
            assert (ours.measured, ours.estimated, ours.free) == (theirs.measured, theirs.estimated, theirs.free)
            assert ours.percent(1234) == theirs.percent(1234) and ours.share(1234) == theirs.share(1234)


def test_the_values_compare_by_content_and_can_be_built_by_hand():
    now = datetime(2026, 1, 1)

    assert SessionInfo("a", None, now, now) == SessionInfo("a", None, now, now)
    assert ModelInfo("m", "m", 1000, False, ("low",)) != ModelInfo("m", "m", 1000, False, ("low",), active=True)
    assert Message("user", "hi") == Message("user", "hi")
    assert Compaction("s", 4, 2).kept == 2
    assert ContextShare("Tool output", 12).items == 0
