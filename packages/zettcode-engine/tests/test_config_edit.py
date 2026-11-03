"""Editing the models in the config file touches the models and nothing else."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest
from zett_agent.model import ReasoningEffort

from zettcode._compat import tomllib
from zettcode.config import ModelConfig
from zettcode.config_edit import (
    ConfigEditError,
    add_model,
    entry_from_model,
    file_entries,
    remove_model,
    render_entry,
    replace_model,
    set_boolean,
    set_string_list,
    toml_string,
    write_text_atomically,
)

WHERE = Path("config.toml")

#: A file like the ones people keep: a banner, comments inside and between blocks, other tables.
HAND_WRITTEN = """\
# ZettCode config -- mine
# keep this banner

# the first one
[[models]]
model = "gpt-5-mini"
token = "sk-one"   # my work key

# the second, via a proxy
[[models]]
model = "gpt-4o"
display_model = "GPT-4o"
token = "sk-two"
base_url = "https://proxy.example.com/v1"
multimodal = true

[skills]
# where my skills live
roots = ["~/my-skills"]

[plugins]
disable = ["noisy"]
"""

NEW = {"model": "deepseek-chat", "token": "sk-new", "base_url": "https://api.deepseek.com"}


def _models(text: str) -> list[dict]:
    return tomllib.loads(text)["models"]


def _others(text: str) -> dict:
    return {key: value for key, value in tomllib.loads(text).items() if key != "models"}


# -- rendering --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["plain", 'has "quotes"', "back\\slash", "tab\there", "new\nline", "bell\x07", "unicode 你好 é", "", "a" * 500],
)
def test_a_string_survives_a_round_trip_through_toml(value):
    assert tomllib.loads(f"key = {toml_string(value)}")["key"] == value


def test_an_entry_renders_in_the_documented_order_and_parses_back_equal():
    entry = {"multimodal": True, "token": "t", "model": "m", "display_model": "M", "base_url": "https://x.example/v1"}

    text = render_entry(entry)

    assert text.splitlines()[0] == "[[models]]"
    assert [line.split(" = ")[0] for line in text.splitlines()[1:]] == [
        "display_model", "model", "base_url", "token", "multimodal",
    ]  # fmt: skip
    assert tomllib.loads(text)["models"] == [entry]


def test_an_unknown_key_is_refused_rather_than_written_where_the_loader_would_reject_it():
    with pytest.raises(ConfigEditError, match="unknown model keys: colour"):
        render_entry({"model": "m", "token": "t", "colour": "red"})


def test_a_value_it_cannot_write_is_refused():
    with pytest.raises(ConfigEditError, match="cannot write"):
        render_entry({"model": "m", "token": {"a": 1}})
    with pytest.raises(ConfigEditError, match="cannot write"):
        render_entry({"model": "m", "token": [1]})


def test_the_levels_a_model_takes_are_written_and_read_back_in_the_documented_place():
    model = ModelConfig(model="m", token="t", reasoning_efforts=(ReasoningEffort.LOW, ReasoningEffort.HIGH))

    entry = entry_from_model(model)
    text = render_entry(entry)

    assert entry["reasoning_efforts"] == ["low", "high"]
    assert text.splitlines()[-1] == 'reasoning_efforts = ["low", "high"]'
    assert tomllib.loads(text)["models"] == [entry]


def test_editing_a_model_in_the_panel_does_not_drop_the_levels_it_takes():
    """The panel rewrites a model from the keys the file holds; a key it did not write would silently vanish."""
    text = '[[models]]\nmodel = "m"\ntoken = "t"\nreasoning_efforts = ["low", "high"]\n'
    entry = dict(file_entries(text, where=WHERE)[0])
    entry["display_model"] = "Renamed"

    result = replace_model(text, 0, entry, where=WHERE)

    assert tomllib.loads(result)["models"][0]["reasoning_efforts"] == ["low", "high"]
    assert tomllib.loads(result)["models"][0]["display_model"] == "Renamed"


def test_a_model_becomes_only_the_keys_that_are_not_defaults():
    model = ModelConfig(model="m", token="t")

    assert entry_from_model(model) == {"model": "m", "token": "t"}


def test_every_setting_of_a_model_is_written_when_it_is_not_the_default():
    model = ModelConfig(
        model="m", token="t", display_model="M", base_url="https://x.example", anthropic=True, multimodal=True,
        context_window=1000, compact_percent=50.0,
    )  # fmt: skip

    assert entry_from_model(model) == {
        "model": "m", "token": "t", "display_model": "M", "base_url": "https://x.example", "anthropic": True,
        "multimodal": True, "context_window": 1000, "compact_percent": 50.0,
    }  # fmt: skip


# -- adding ----------------------------------------------------------------------------------------


def test_adding_keeps_every_byte_of_the_file_it_was_given():
    result = add_model(HAND_WRITTEN, NEW, where=WHERE)

    assert "# ZettCode config -- mine\n# keep this banner" in result
    assert 'token = "sk-one"   # my work key' in result
    assert "# the second, via a proxy" in result
    assert "# where my skills live" in result
    assert _others(result) == _others(HAND_WRITTEN)


def test_adding_puts_the_new_model_after_the_last_and_before_the_next_table():
    result = add_model(HAND_WRITTEN, NEW, where=WHERE)

    assert [m["model"] for m in _models(result)] == ["gpt-5-mini", "gpt-4o", "deepseek-chat"]
    assert result.index("deepseek-chat") < result.index("[skills]")
    assert result.index("multimodal = true") < result.index("deepseek-chat")


def test_adding_leaves_the_comments_that_introduce_the_next_table_with_it():
    result = add_model(HAND_WRITTEN, NEW, where=WHERE)

    assert result.index("deepseek-chat") < result.index("[skills]\n# where my skills live")


def test_adding_to_a_file_that_ends_with_its_last_model_appends_it():
    text = '[[models]]\nmodel = "a"\ntoken = "t"\n'

    result = add_model(text, NEW, where=WHERE)

    assert [m["model"] for m in _models(result)] == ["a", "deepseek-chat"]
    assert result.startswith(text.rstrip("\n"))


def test_adding_works_on_a_file_with_windows_line_endings():
    text = HAND_WRITTEN.replace("\n", "\r\n")

    result = add_model(text, NEW, where=WHERE)

    assert [m["model"] for m in _models(result)] == ["gpt-5-mini", "gpt-4o", "deepseek-chat"]
    assert _others(result) == _others(text)


def test_adding_twice_adds_two():
    once = add_model(HAND_WRITTEN, NEW, where=WHERE)
    twice = add_model(once, {"model": "other", "token": "t"}, where=WHERE)

    assert [m["model"] for m in _models(twice)][-2:] == ["deepseek-chat", "other"]


def test_the_same_model_may_be_added_twice_against_different_endpoints():
    twice = add_model(HAND_WRITTEN, {"model": "gpt-4o", "token": "t", "base_url": "https://b.example/v1"}, where=WHERE)

    assert [m["model"] for m in _models(twice)].count("gpt-4o") == 2


def test_an_entry_the_loader_would_refuse_is_refused_before_anything_is_written():
    with pytest.raises(ConfigEditError, match="cannot use both APIs"):
        add_model(HAND_WRITTEN, {"model": "m", "token": "t", "anthropic": True, "responses_api": True}, where=WHERE)


def test_an_entry_with_a_blank_model_is_refused():
    with pytest.raises(ConfigEditError):
        add_model(HAND_WRITTEN, {"model": "  ", "token": "t"}, where=WHERE)


def test_a_token_with_quotes_and_backslashes_is_written_so_it_reads_back_identically():
    nasty = 'p"a\\ss\tword'

    result = add_model(HAND_WRITTEN, {"model": "m", "token": nasty}, where=WHERE)

    assert _models(result)[-1]["token"] == nasty


# -- replacing -------------------------------------------------------------------------------------


def test_replacing_rewrites_only_that_block():
    result = replace_model(HAND_WRITTEN, 1, {"model": "gpt-4o", "token": "sk-new-two"}, where=WHERE)

    assert [m.get("token") for m in _models(result)] == ["sk-one", "sk-new-two"]
    assert 'token = "sk-one"   # my work key' in result, "the other block's own comment stays"
    assert "# the second, via a proxy" in result, "and so does the comment above the one that changed"
    assert _others(result) == _others(HAND_WRITTEN)
    assert "# where my skills live" in result


def test_replacing_the_first_leaves_the_second_exactly_as_written():
    result = replace_model(HAND_WRITTEN, 0, {"model": "gpt-5", "token": "t"}, where=WHERE)

    second = HAND_WRITTEN[HAND_WRITTEN.index("# the second") :]
    assert second in result


def test_replacing_a_model_that_is_not_there_is_refused():
    with pytest.raises(ConfigEditError, match="no model number 3"):
        replace_model(HAND_WRITTEN, 2, NEW, where=WHERE)
    with pytest.raises(ConfigEditError, match="no model number 0"):
        replace_model(HAND_WRITTEN, -1, NEW, where=WHERE)


# -- removing --------------------------------------------------------------------------------------


def test_removing_takes_the_block_and_the_blank_line_that_set_it_apart():
    result = remove_model(HAND_WRITTEN, 1, where=WHERE)

    assert [m["model"] for m in _models(result)] == ["gpt-5-mini"]
    assert "\n\n\n" not in result, "no gap left behind"
    assert "gpt-4o" not in result
    assert _others(result) == _others(HAND_WRITTEN)
    assert "# where my skills live" in result and "# my work key" in result


def test_removing_the_first_keeps_the_banner():
    result = remove_model(HAND_WRITTEN, 0, where=WHERE)

    assert [m["model"] for m in _models(result)] == ["gpt-4o"]
    assert result.startswith("# ZettCode config -- mine\n# keep this banner")


def test_the_only_model_cannot_be_removed_because_the_program_would_not_start():
    text = '[[models]]\nmodel = "a"\ntoken = "t"\n'

    with pytest.raises(ConfigEditError, match="only model"):
        remove_model(text, 0, where=WHERE)


def test_removing_a_model_that_is_not_there_is_refused():
    with pytest.raises(ConfigEditError, match="no model number 5"):
        remove_model(HAND_WRITTEN, 4, where=WHERE)


def test_adding_then_removing_gives_back_the_file():
    added = add_model(HAND_WRITTEN, NEW, where=WHERE)

    assert remove_model(added, 2, where=WHERE) == HAND_WRITTEN


# -- layouts it must not guess at ---------------------------------------------------------------------


def test_a_file_that_writes_its_models_as_an_inline_array_is_refused_not_mangled():
    text = 'models = [{ model = "a", token = "t" }, { model = "b", token = "t" }]\n[skills]\nenabled = true\n'

    with pytest.raises(ConfigEditError, match="edit the file by hand"):
        add_model(text, NEW, where=WHERE)


def test_a_file_that_is_not_toml_is_refused_with_its_name():
    with pytest.raises(ConfigEditError, match="config.toml is not valid TOML"):
        add_model("[[models\nmodel = ", NEW, where=WHERE)


def test_a_file_with_no_models_is_where_the_first_one_is_written():
    """A fresh machine has no ``[[models]]`` table, and ``/config add`` is how it gets one: writing it into a file
    that has nothing else works, and leaves everything else the file holds where it was."""
    text = "[skills]\nenabled = true\n"

    assert file_entries(text, where=WHERE) == []
    written = add_model(text, NEW, where=WHERE)

    assert file_entries(written, where=WHERE) == [dict(NEW)]
    assert "[skills]\nenabled = true" in written, "the settings that were there are still there"
    assert written.index("[[models]]") > written.index("enabled = true"), "the entry goes at the end"
    assert "\n\n[[models]]" in written and "\n\n\n" not in written, "one blank line sets it apart, and one only"


@pytest.mark.parametrize("text", ["", "\n\n"])
def test_the_first_entry_into_an_empty_file_starts_at_the_top(text):
    """An empty or whitespace-only file gets no leading blank line: the block is the first thing in it."""
    written = add_model(text, NEW, where=WHERE)

    assert written.startswith("[[models]]"), written
    assert file_entries(written, where=WHERE) == [dict(NEW)]


def test_the_first_entry_after_a_comment_keeps_the_comment_first_and_gets_one_blank_line():
    written = add_model("# my config\n", NEW, where=WHERE)

    assert written.startswith("# my config\n\n[[models]]"), written
    assert file_entries(written, where=WHERE) == [dict(NEW)]


def test_the_first_entry_after_a_file_that_ends_without_a_newline_still_gets_a_blank_line():
    written = add_model("[skills]\nenabled = true", NEW, where=WHERE)

    assert "\n\n[[models]]" in written, "a block set against the last key is not what a reader expects"
    assert file_entries(written, where=WHERE) == [dict(NEW)]


def test_a_file_that_writes_models_as_a_value_cannot_be_added_to():
    """`models = []` and `[[models]]` are the same key: a block cannot be written beside the array."""
    with pytest.raises(ConfigEditError, match="writes 'models' as a value"):
        add_model("models = []\n[skills]\nenabled = true\n", NEW, where=WHERE)


def test_a_header_inside_a_multi_line_string_is_not_taken_for_a_block():
    text = '[[models]]\nmodel = "a"\ntoken = "t"\n\n[mcp]\nnote = """\n[[models]]\n"""\n'

    with pytest.raises(ConfigEditError):  # the counts disagree, so it refuses instead of cutting the string
        add_model(text, NEW, where=WHERE)


def test_the_models_as_written_leave_a_token_the_environment_provides_absent(monkeypatch):
    text = '[[models]]\nmodel = "a"\n'

    assert file_entries(text, where=WHERE) == [{"model": "a"}]


# -- writing ---------------------------------------------------------------------------------------


def test_writing_replaces_the_file_whole(tmp_path):
    path = tmp_path / "c.toml"
    path.write_text("old", encoding="utf-8")

    write_text_atomically(path, "new\n")

    assert path.read_text(encoding="utf-8") == "new\n"
    assert [p.name for p in tmp_path.iterdir()] == ["c.toml"], "no temporary file is left behind"


def test_writing_creates_the_directory_and_a_private_file(tmp_path):
    path = tmp_path / "deep" / "er" / "c.toml"

    write_text_atomically(path, "x")

    assert path.read_text(encoding="utf-8") == "x"
    if sys.platform != "win32":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600, "a file that holds tokens starts private"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_writing_keeps_the_permissions_the_reader_chose(tmp_path):
    path = tmp_path / "c.toml"
    path.write_text("old", encoding="utf-8")
    os.chmod(path, 0o640)

    write_text_atomically(path, "new")

    assert stat.S_IMODE(path.stat().st_mode) == 0o640


def test_a_write_that_fails_leaves_the_old_file_and_no_debris(tmp_path, monkeypatch):
    path = tmp_path / "c.toml"
    path.write_text("old", encoding="utf-8")

    def fail(source, target):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", fail)

    with pytest.raises(OSError, match="disk full"):
        write_text_atomically(path, "new")

    assert path.read_text(encoding="utf-8") == "old"
    assert [p.name for p in tmp_path.iterdir()] == ["c.toml"]


def test_writing_does_not_translate_line_endings(tmp_path):
    path = tmp_path / "c.toml"

    write_text_atomically(path, "a\r\nb\r\n")

    assert path.read_bytes() == b"a\r\nb\r\n"


# -- the check made before anything is written ---------------------------------------------------------------
#
# The edits above are made on text, so a bug in them would write a file that is wrong. `_checked` is what
# stands between such a bug and the disk; it can only be seen working by handing it a result that is wrong.


def _checked(new_text: str, original: str = HAND_WRITTEN, *, expected: list[dict] | None = None) -> None:
    from zettcode.config_edit import _checked as check

    before = tomllib.loads(original)
    check(new_text, before, before["models"] if expected is None else expected, WHERE)


def test_the_check_passes_a_result_that_is_what_was_meant():
    _checked(HAND_WRITTEN)


def test_the_check_refuses_a_result_that_changed_another_table():
    damaged = HAND_WRITTEN.replace('disable = ["noisy"]', "disable = []")

    with pytest.raises(ConfigEditError, match="something other than the models"):
        _checked(damaged)


def test_the_check_refuses_a_result_that_lost_a_table():
    with pytest.raises(ConfigEditError, match="something other than the models"):
        _checked(HAND_WRITTEN[: HAND_WRITTEN.index("[plugins]")])


def test_the_check_refuses_a_result_with_the_wrong_models():
    damaged = HAND_WRITTEN.replace('token = "sk-one"', 'token = "sk-other"')

    with pytest.raises(ConfigEditError, match="did not produce the models it meant"):
        _checked(damaged)


def test_the_check_refuses_a_result_with_an_extra_model():
    with pytest.raises(ConfigEditError, match="did not produce the models it meant"):
        _checked(HAND_WRITTEN + '\n[[models]]\nmodel = "x"\ntoken = "t"\n')


def test_the_check_refuses_a_result_that_is_not_toml():
    with pytest.raises(ConfigEditError, match="not valid TOML"):
        _checked(HAND_WRITTEN + "\n[[models\n")


def test_the_check_refuses_models_the_loader_would_refuse():
    both = {"model": "m", "token": "t", "anthropic": True, "responses_api": True}

    with pytest.raises(ConfigEditError, match="cannot use both APIs"):
        _raise_from_loader(both)


def _raise_from_loader(entry: dict) -> None:
    from zettcode.config_edit import _checked as check

    text = render_entry(entry)
    check(text, {"models": [entry]}, [entry], WHERE)


def test_a_buggy_edit_is_stopped_before_it_is_written(monkeypatch):
    """The whole point: if the edit itself is wrong, nothing reaches the disk."""
    from zettcode import config_edit

    monkeypatch.setattr(config_edit, "_blocks", lambda lines: [(0, 1), (1, 2)])  # wrong boundaries

    with pytest.raises(ConfigEditError):
        remove_model(HAND_WRITTEN, 0, where=WHERE)


# -- a table the file opens only through its sub-tables -------------------------------------------------

#: ``[plugins.recap]`` makes a ``plugins`` table without any line saying ``[plugins]``; this is the file the
#: documentation tells a reader to write, and the one `/plugins` could not switch a plugin in.
ONLY_SUBTABLES = (
    '[[models]]\nmodel = "m"\ntoken = "t"\n\n# my recap\n[plugins.recap]\nafter_seconds = 30  # half a minute\n'
)


def test_a_table_the_file_opens_only_through_a_subtable_gets_a_header_of_its_own():
    result = set_string_list(ONLY_SUBTABLES, "plugins", "disable", ["greeter"], where=WHERE, command="/plugins")

    assert tomllib.loads(result)["plugins"] == {"disable": ["greeter"], "recap": {"after_seconds": 30}}
    # Nothing the reader wrote moved or changed: the original is the start of the result, byte for byte.
    assert result.startswith(ONLY_SUBTABLES.rstrip("\n"))


def test_the_second_switch_goes_under_the_header_the_first_one_added():
    once = set_string_list(ONLY_SUBTABLES, "plugins", "disable", ["a"], where=WHERE, command="/plugins")
    twice = set_string_list(once, "plugins", "disable", ["a", "b"], where=WHERE, command="/plugins")

    assert twice.count("[plugins]") == 1
    assert tomllib.loads(twice)["plugins"] == {"disable": ["a", "b"], "recap": {"after_seconds": 30}}


def test_the_header_is_added_for_a_boolean_too():
    text = '[[models]]\nmodel = "m"\ntoken = "t"\n\n[harness.child]\nx = 1\n'

    result = set_boolean(text, "harness", "subagent", False, where=WHERE, command="/plugins")

    assert tomllib.loads(result)["harness"] == {"subagent": False, "child": {"x": 1}}


@pytest.mark.parametrize(
    "text",
    [
        pytest.param('plugins.disable = []\n\n[[models]]\nmodel = "m"\ntoken = "t"\n', id="dotted-key"),
        pytest.param(
            'plugins.a.b = 1\n\n[[models]]\nmodel = "m"\ntoken = "t"\n\n[plugins.recap]\nc = 1\n', id="dotted+sub"
        ),
        pytest.param('plugins = { recap = { a = 1 } }\n\n[[models]]\nmodel = "m"\ntoken = "t"\n', id="inline"),
        pytest.param('[[models]]\nmodel = "m"\ntoken = "t"\n\n[[plugins.x]]\na = 1\n', id="array-of-tables"),
        pytest.param(
            '[[models]]\nmodel = "m"\ntoken = "t"\n\n[plugins.disable]\nx = 1\n', id="subtable-named-like-key"
        ),
        # A quoted first segment is recognised, so these are refused before any append is tried.
        pytest.param('"plugins" = { recap = { a = 1 } }\n\n[[models]]\nmodel = "m"\ntoken = "t"\n', id="inline-quoted"),
        pytest.param(
            '[[models]]\nmodel = "m"\ntoken = "t"\n\n["plugins"]\nx = 1\n\n["plugins".recap]\na = 1\n', id="quoted"
        ),
        # A key spelled with an escape is `plugins` to TOML and nothing the line patterns can see: the append IS
        # attempted, the result does not parse, and that must still read as "we cannot edit this", not as a fault in
        # the reader's file.
        pytest.param(
            '"plug\\u0069ns" = { recap = { a = 1 } }\n\n[[models]]\nmodel = "m"\ntoken = "t"\n', id="escaped-key"
        ),
    ],
)
def test_a_table_declared_any_other_way_is_still_left_for_the_reader(text):
    """A second ``[plugins]`` would be invalid TOML after these, so the edit is refused instead of attempted.

    The whole message is matched, and the one the reader's file would earn is ruled out: a loose pattern let "we
    understood and refused" and "we wrote TOML we could not read back" pass for each other.
    """
    with pytest.raises(ConfigEditError) as refused:
        set_string_list(text, "plugins", "disable", ["greeter"], where=WHERE, command="/plugins")

    assert str(refused.value) == f"{WHERE} writes [plugins] in a way /plugins cannot edit safely; edit the file by hand"


@pytest.mark.parametrize(
    "header",
    [
        pytest.param("[plugins.recap]", id="bare"),
        pytest.param('["plugins".recap]', id="quoted-first-segment"),
        pytest.param("[ plugins . recap ]", id="spaces-around-dots"),
        pytest.param("[plugins.'recap']", id="quoted-last-segment"),
    ],
)
@pytest.mark.parametrize("ending", ["\n", ""], ids=["trailing-newline", "no-trailing-newline"])
def test_the_header_is_added_however_the_subtable_is_spelled_and_the_file_ends(header, ending):
    """The reader's text stays exactly as written, byte for byte, whichever way the sub-table is spelled."""
    text = f'[[models]]\nmodel = "m"\ntoken = "t"\n\n{header}\nafter_seconds = 30{ending}'

    result = set_string_list(text, "plugins", "disable", ["greeter"], where=WHERE, command="/plugins")

    assert result.startswith(text.rstrip("\n"))
    assert tomllib.loads(result)["plugins"] == {"disable": ["greeter"], "recap": {"after_seconds": 30}}
