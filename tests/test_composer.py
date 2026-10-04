"""The composer: a text area that stands a large paste in for itself."""

from __future__ import annotations

import base64

from zettcode.app.ui.widgets import Composer
from zettcode.tui import DARK
from zettcode.tui.testing import Harness


def _block(lines: int = 30) -> str:
    """Return a paste big enough to become a chip."""
    return "\n".join(f"line {index}" for index in range(lines))


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
