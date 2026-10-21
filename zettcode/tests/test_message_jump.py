"""Alt (or Ctrl) with Up and Down walks back and forth through the messages the reader sent."""

from __future__ import annotations

from test_zettcode_app import _harness, build_app


def conversation(count: int = 5, lines: int = 14):
    """A shell with ``count`` exchanges, each a message of the reader's and an answer ``lines`` rows long."""
    app = build_app()
    harness = _harness(app)
    harness.resize(100, 30)
    for number in range(count):
        app.transcript.user_message(f"question {number}")
        app.transcript.append_answer("\n\n".join(f"answer {number} part {part}" for part in range(lines)))
    harness.render()
    return app, harness


def starts(app) -> list[int]:
    return app.view.transcript_source.user_starts(app.view.line_width)


def test_the_view_knows_where_each_message_the_reader_sent_begins_and_leaves_a_side_question_out():
    app, harness = conversation(3)
    app.transcript.user_message("by the way", side=True)
    app.transcript.append_answer("an aside")
    harness.render()

    found = starts(app)

    assert len(found) == 3 and found == sorted(found)
    for number, start in enumerate(found):
        # A message's block may open with a row of space, so look at the rows it begins with.
        rows = [app.view.source.line(start + offset, app.view.line_width).text for offset in range(3)]
        assert any(f"question {number}" in row for row in rows), rows


def test_alt_up_goes_to_the_message_before_the_top_of_the_view_and_again_to_the_one_before_that():
    app, harness = conversation()
    view = app.view
    found = starts(app)
    assert view.follow_tail and view.top > found[-1], "the newest answer is long enough to push the last message off"

    harness.press("alt_up")
    harness.render()
    assert view.top == found[-1] and not view.follow_tail

    harness.press("alt_up")
    harness.render()
    assert view.top == found[-2]

    for expected in reversed(found[:-2]):
        harness.press("alt_up")
        harness.render()
        assert view.top == expected


def test_alt_up_from_above_the_first_message_goes_to_the_top_and_then_stays():
    app, harness = conversation()
    for _ in range(len(starts(app)) + 1):
        harness.press("alt_up")
        harness.render()

    assert app.view.top == 0
    harness.press("alt_up")
    harness.render()
    assert app.view.top == 0


def test_alt_down_walks_forward_and_after_the_last_message_returns_to_the_newest_line():
    app, harness = conversation()
    view = app.view
    found = starts(app)
    view.scroll_to(found[0])
    harness.render()

    harness.press("alt_down")
    harness.render()
    assert view.top == found[1], "the first message is at the top already, so the next is the second"
    for _ in range(len(found) - 2):
        harness.press("alt_down")
        harness.render()
    assert view.top == found[-1] and not view.follow_tail

    harness.press("alt_down")
    harness.render()
    assert view.follow_tail, "past the last message the view follows the newest line again"
    harness.press("alt_down")
    harness.render()
    assert view.follow_tail


def test_ctrl_up_and_ctrl_down_do_the_same():
    """VS Code's terminal sends Option-Up as the bytes of Ctrl-Up, so both spellings are one key."""
    app, harness = conversation()
    found = starts(app)

    harness.press("ctrl_up")
    harness.render()
    assert app.view.top == found[-1]
    harness.press("ctrl_down")
    harness.render()
    assert app.view.follow_tail


def test_the_keys_belong_to_the_follow_up_list_while_it_has_something_in_it():
    from zettcode.app.ui.followups import FollowUp

    app, harness = conversation()
    app._follow_ups.append(FollowUp("later", ()))  # a message waiting to be sent after the running request

    harness.press("alt_up")
    harness.render()

    assert app._follow_up_selecting, "the key walked into the list"
    assert app.view.follow_tail, "and the transcript did not go back to a message"


def test_the_message_box_does_not_take_the_key_as_history_and_the_draft_is_untouched():
    app, harness = conversation()
    harness.write("half a thought")

    harness.press("alt_up")
    harness.render()

    assert app.composer.text == "half a thought"
    assert app.view.top == starts(app)[-1]


def test_with_no_messages_there_is_nowhere_to_go_and_nothing_breaks():
    app = build_app()
    harness = _harness(app)
    harness.resize(100, 30)
    harness.render()

    harness.press("alt_up")
    harness.press("alt_down")
    harness.render()

    assert app.view.top == 0 and app.view.follow_tail
