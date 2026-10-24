"""The composer: a text area that stands a large paste in for itself."""

from __future__ import annotations

import base64

from zettcode.app.ui.widgets import Composer
from zettcode.engine.agent.prompt import MentionPart
from zettcode.tui import DARK, Style
from zettcode.tui.testing import Harness


def _block(lines: int = 30) -> str:
    """Return a paste big enough to become a chip."""
    return "\n".join(f"line {index}" for index in range(lines))


def test_a_draft_is_split_at_its_mentions():
    composer = Composer()
    composer.set_text("please @note this /help")

    assert composer.parts() == ("please ", MentionPart(token="@note"), " this /help")


def test_a_paste_over_the_character_limit_becomes_one_chip():
    submitted: list[str] = []
    composer = Composer(on_submit=lambda text: submitted.append(text) or True)
    harness = Harness(composer, width=60, height=6)
    block = "x" * (Composer.PASTE_CHIP_CHARS + 1)

    harness.paste(block)

    assert composer.text == f"[pasted text {len(block)} chars]"
    assert composer.value == block

    harness.press("enter")

    assert submitted == [block]


def test_a_paste_taller_than_the_editor_becomes_one_chip():
    """Rows count too: a paste that would scroll the draft hides it just as well."""
    composer = Composer(max_height=4)

    composer.paste(_block(4))  # four rows fit the editor as it is
    assert composer.pastes == {}
    composer.clear()
    composer.paste(_block(5))

    assert composer.text.startswith("[pasted text ")
    assert composer.value == _block(5)


def test_a_small_paste_goes_in_as_text():
    composer = Composer()

    composer.paste("print('hi')\n")

    assert composer.text == "print('hi')\n"
    assert composer.value == composer.text


def test_backspace_removes_a_chip_in_one_press():
    composer = Composer()
    harness = Harness(composer, width=60, height=4)
    composer.paste(_block())

    harness.press("backspace")

    assert composer.text == ""
    assert composer.value == ""

    # Undo puts the chip back with the text it stood for.
    harness.press("ctrl_z")

    assert composer.text.startswith("[pasted text ")
    assert composer.value == _block()


def test_two_pastes_of_the_same_size_keep_their_own_text():
    composer = Composer()
    first, second = "a" * 600, "b" * 600

    composer.paste(first)
    composer.paste(second)

    assert composer.text == "[pasted text 600 chars][pasted text 600 chars #2]"
    assert composer.value == first + second


def test_editing_into_a_chip_turns_it_back_into_text():
    composer = Composer()
    composer.paste(_block())
    composer.position = len("[pasted text ") + 2

    Harness(composer, width=60, height=4).press("backspace")

    assert composer.value == composer.text  # the label is literal now


def test_replacing_the_draft_drops_the_text_a_chip_stood_for():
    composer = Composer()
    composer.paste(_block())
    block = _block()

    composer.set_text(block)

    assert composer.text.startswith("[pasted text ")  # a recalled draft is chipped again
    assert composer.value == block

    composer.clear()

    assert composer.pastes == {}


def test_a_chip_is_painted_as_an_aside():
    composer = Composer()
    composer.paste(_block())

    styled = Harness(composer, width=60, height=4).render().styled

    chip = [span for span in styled[0] if "pasted text" in span.text]
    assert chip
    assert all(span.style.foreground == DARK.warning and span.style.bold for span in chip)


def test_an_image_chip_stands_for_the_clipboard_bytes():
    composer = Composer()
    harness = Harness(composer, width=40, height=3)

    composer.attach_image(b"png-bytes", "image/png")

    assert composer.text == "[image #1]"
    assert composer.parts() == ("[image #1]", (b"png-bytes", "image/png"))
    chip = [span for span in harness.render().styled[0] if "image #1" in span.text]
    assert chip and chip[0].style.foreground == DARK.warning

    # Deleting the chip takes it out of the message, and undo puts it back.
    harness.press("backspace")
    assert composer.parts() == ()
    harness.press("ctrl_z")
    assert composer.parts() == ("[image #1]", (b"png-bytes", "image/png"))


def test_parts_keep_text_and_images_in_the_order_they_were_written():
    composer = Composer()
    harness = Harness(composer, width=80, height=6)

    harness.write("before ")
    composer.attach_image(b"first", "image/png")
    harness.write(" between ")
    composer.attach_image(b"second", "image/png")
    harness.write(" after")

    assert composer.text == "before [image #1] between [image #2] after"
    assert composer.parts() == (
        "before [image #1]",
        (b"first", "image/png"),
        " between [image #2]",
        (b"second", "image/png"),
        " after",
    )


def test_a_pasted_chip_is_expanded_inside_the_part_it_sits_in():
    composer = Composer()
    harness = Harness(composer, width=80, height=6)
    block = _block()

    harness.write("look: ")
    composer.paste(block)
    harness.write(" done")

    assert composer.parts() == (f"look: {block} done",)


def test_a_pasted_base64_image_becomes_an_image_chip_not_a_text_chip():
    """VS Code pastes a clipboard image as base64 text; that is still a picture."""
    composer = Composer()
    data = b"\x89PNG\r\n\x1a\n" + b"pixels" * 60

    composer.paste("data:image/png;base64," + base64.b64encode(data).decode())

    assert composer.text == "[image #1]"
    assert composer.pastes == {}
    assert composer.parts() == ("[image #1]", (data, "image/png"))


def test_a_base64_paste_that_is_not_an_image_is_still_a_text_chip():
    composer = Composer()
    blob = base64.b64encode(b"print('hello')\n" * 200).decode()

    composer.paste(blob)

    assert composer.pastes == {f"[pasted text {len(blob)} chars]": blob}
    assert composer.text.startswith("[pasted text ")


# -- only what exists is painted and taken whole: a word that merely looks like a command is a word ------


def _painted(composer: Composer, text: str) -> dict[str, object]:
    composer.set_text(text)
    # Only what was given a colour: the body of the draft comes back as spans too, with none.
    return {
        span.text: span.style.foreground
        for span in composer.spans_for(text, 0, Style())
        if span.style.foreground is not None
    }


def _composer(*, commands=("/help", "/model"), mentions=("@note", "@src/app.py")) -> Composer:
    composer = Composer()
    Harness(composer, width=40, height=4, theme=DARK)
    composer.is_command = lambda name: name in commands
    composer.is_mention = lambda token: token in mentions
    return composer


def test_a_command_and_a_reference_that_exist_are_painted_apart_from_the_body():
    styles = _painted(_composer(), "/help @note")

    assert styles["/help"] == DARK.accent
    assert styles["@note"] == DARK.accent_bright


def test_a_command_that_does_not_exist_is_not_painted():
    assert "/nope" not in _painted(_composer(), "/nope")


def test_a_reference_that_does_not_exist_is_not_painted():
    styles = _painted(_composer(), "look at @missing and @note")

    assert "@missing" not in styles
    assert styles["@note"] == DARK.accent_bright, "and one that does is, wherever it is"


def test_a_command_that_is_not_the_first_word_is_not_painted_because_it_would_not_run():
    """`value.partition(" ")` is where a command is recognised: the first word, and nowhere else."""
    composer = _composer()

    assert "/help" not in _painted(composer, "please run /help")
    assert _painted(composer, "  /help me")["/help"] == DARK.accent, "leading space does not stop one"


def test_a_path_is_not_taken_for_a_command_even_when_a_command_of_that_name_exists():
    assert "/help" not in _painted(_composer(), "src/help is a path")
    assert "/help" not in _painted(_composer(), "src/help")


def test_a_reference_is_painted_the_moment_it_becomes_real_and_not_before():
    composer = _composer()

    assert "@no" not in _painted(composer, "@no")
    assert _painted(composer, "@note")["@note"] == DARK.accent_bright


def test_backspace_takes_a_command_or_reference_that_exists_whole():
    for text, expected in (("你好 @note", "你好 "), ("/help", ""), ("see @src/app.py", "see "), ("/model", "")):
        composer = _composer()
        harness = Harness(composer, width=40, height=4)
        composer.is_command, composer.is_mention = _composer().is_command, _composer().is_mention
        harness.write(text)

        harness.press("backspace")

        assert composer.text == expected, text


def test_backspace_peels_a_word_that_only_looks_like_one_a_character_at_a_time():
    for text, expected in (("/nope", "/nop"), ("@missing", "@missin"), ("see @nothing", "see @nothin"), ("abc", "ab")):
        composer = _composer()
        harness = Harness(composer, width=40, height=4)
        harness.write(text)

        harness.press("backspace")

        assert composer.text == expected, text


def test_backspace_in_the_middle_of_a_real_reference_is_one_character_like_anywhere_else():
    composer = _composer()
    harness = Harness(composer, width=40, height=4)
    harness.write("@note")
    harness.press("left")

    harness.press("backspace")

    assert composer.text == "@noe", "the t before the cursor, not the whole reference"


def test_backspace_after_a_real_command_in_the_middle_of_a_sentence_is_one_character():
    """It is not a command there, so it is not one token."""
    composer = _composer()
    harness = Harness(composer, width=40, height=4)
    harness.write("run /help")

    harness.press("backspace")

    assert composer.text == "run /hel"


def test_the_painting_and_backspace_agree_for_every_prefix_of_a_draft():
    """What was painted as a unit is what Backspace removes as one, at every cursor position."""
    composer = _composer()
    draft = "/help then @note and @missing /nope"
    for cut in range(1, len(draft) + 1):
        composer.set_text(draft[:cut])
        painted_ends = {end for _, end, _ in composer._token_hits()}
        token = composer._token_before()

        assert (token is not None) == (composer.position in painted_ends), draft[:cut]


def test_the_lookup_is_made_once_per_draft_however_many_rows_ask():
    asked: list[str] = []
    composer = Composer()
    Harness(composer, width=40, height=4, theme=DARK)
    composer.is_mention = lambda token: asked.append(token) or True
    composer.set_text("@note is here")

    for _ in range(5):
        composer.spans_for("@note is here", 0, Style())
    composer._token_before()

    assert asked == ["@note"]


def test_the_lookup_is_made_again_when_the_draft_changes():
    asked: list[str] = []
    composer = Composer()
    Harness(composer, width=40, height=4, theme=DARK)
    composer.is_mention = lambda token: asked.append(token) or False
    composer.set_text("@a")
    composer.spans_for("@a", 0, Style())

    composer.set_text("@ab")
    composer.spans_for("@ab", 0, Style())

    assert asked == ["@a", "@ab"]


def test_an_editor_that_knows_no_commands_still_paints_the_way_it_always_did():
    """The defaults accept everything, so a bare composer — tests, other hosts — is unchanged."""
    composer = Composer()
    Harness(composer, width=30, height=3, theme=DARK)

    styles = _painted(composer, "/help @note")

    assert styles["/help"] == DARK.accent and styles["@note"] == DARK.accent_bright


# -- restore: a message's parts put back as a draft ---------------------------------------------------------

PNG = (b"\x89PNG\r\n\x1a\n" + b"1", "image/png")
JPEG = (b"\xff\xd8\xff" + b"2", "image/jpeg")


def test_restoring_text_is_setting_it():
    composer = Composer()
    Harness(composer, width=40, height=4)

    composer.restore(("fix the ", "parser"))

    assert composer.text == "fix the parser" and composer.position == len("fix the parser")


def test_restoring_a_message_with_a_picture_gives_the_picture_its_chip_back():
    composer = Composer()
    Harness(composer, width=60, height=4)

    composer.restore(("compare [image #1]", PNG, " with the code"))

    assert composer.text == "compare [image #1] with the code"
    assert composer.images == {"[image #1]": PNG}


def test_what_parts_returned_restore_puts_back_exactly():
    composer = Composer()
    Harness(composer, width=60, height=4)
    composer.paste("look at ")
    composer.attach_image(*PNG)
    composer.paste(" and ")
    composer.attach_image(*JPEG)
    parts = composer.parts()

    other = Composer()
    Harness(other, width=60, height=4)
    other.restore(parts)

    assert other.parts() == parts
    assert other.text == composer.text and other.images == composer.images


def test_two_messages_that_were_both_written_with_image_one_do_not_collide_when_joined():
    """Each message numbered its own pictures from one; in one draft they cannot both be one."""
    composer = Composer()
    Harness(composer, width=80, height=4)

    composer.restore(("first [image #1]", PNG, "\n\n", "second [image #1]", JPEG))

    assert composer.text == "first [image #1]\n\nsecond [image #2]"
    assert composer.images == {"[image #1]": PNG, "[image #2]": JPEG}
    assert composer.parts() == ("first [image #1]", PNG, "\n\nsecond [image #2]", JPEG)


def test_a_mention_in_the_parts_is_restored_as_the_text_it_was():
    from zettcode.engine.agent.prompt import MentionPart

    composer = Composer()
    Harness(composer, width=60, height=4)

    composer.restore(("read ", MentionPart("@note"), " first"))

    assert composer.text == "read @note first"


def test_a_long_draft_with_a_picture_is_not_chipped_over_the_labels_the_picture_is_known_by():
    composer = Composer()
    Harness(composer, width=60, height=4)
    long = "x" * (Composer.PASTE_CHIP_CHARS + 50)

    composer.restore((long + "[image #1]", PNG))

    assert composer.text == long + "[image #1]" and "[pasted text" not in composer.text
    assert composer.images == {"[image #1]": PNG}


def test_a_long_draft_without_a_picture_is_a_chip_again_as_it_always_was():
    composer = Composer()
    Harness(composer, width=60, height=4)
    long = "x" * (Composer.PASTE_CHIP_CHARS + 50)

    composer.restore((long,))

    assert composer.text.startswith("[pasted text") and composer.value == long


def test_restoring_replaces_what_was_there_pictures_included():
    composer = Composer()
    Harness(composer, width=60, height=4)
    composer.attach_image(*JPEG)

    composer.restore(("only text",))

    assert composer.text == "only text" and composer.images == {}


def test_restoring_tells_the_editor_once_not_once_per_part():
    changes: list[str] = []
    composer = Composer(on_change=lambda: changes.append("changed"))
    Harness(composer, width=60, height=4)
    changes.clear()

    composer.restore(("a [image #1]", PNG, " b [image #2]", JPEG, " c"))

    assert len(changes) == 1, "an observer that clears a half-built draft would abandon an edit"
