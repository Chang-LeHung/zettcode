"""The tool-rendering chain: the words a tool call turns into."""

from __future__ import annotations

from collections.abc import Mapping

from zettcode.app.agent.rendering import (
    ANSWER,
    DEFAULT_RENDERERS,
    THINKING,
    FallbackTool,
    Renderers,
    ToolHandler,
    ToolRow,
    language_for_path,
)


def describe(name: str, **arguments: object) -> str:
    """Return the row title the default chain renders for one call."""
    return DEFAULT_RENDERERS.describe(name, arguments).title


def test_the_chain_phrases_the_coding_tools():
    assert describe("read_file", path="src/app.py") == "Read src/app.py"
    assert describe("write_file", path="notes/plan.md") == "Wrote notes/plan.md"
    assert describe("replace_in_file", path="app.py", edits=[{"old": "a"}, {"old": "b"}]) == "Edited app.py (2 edits)"
    assert describe("replace_in_file", path="app.py", edits=[{"old": "a"}]) == "Edited app.py (1 edit)"
    assert describe("replace_in_file", path="app.py") == "Edited app.py"
    assert describe("delete_file", path="99\u4e58\u6cd5\u8868.txt") == "Deleted 99\u4e58\u6cd5\u8868.txt"
    assert describe("run_shell", command="pwd && ls -la") == "Ran pwd && ls -la"
    assert describe("glob", pattern="**/*.py") == "Listed **/*.py"
    assert describe("grep", pattern="TODO", path="src") == "Searched TODO in src"


def test_a_missing_or_unusable_argument_degrades_to_a_placeholder():
    assert describe("read_file") == "Read (unknown file)"
    assert describe("read_file", path=7) == "Read (unknown file)"
    assert describe("run_shell", command="   ") == "Ran (unknown command)"
    assert describe("glob") == "Listed files"
    assert describe("grep", pattern="x") == "Searched x"


def test_the_chain_never_shows_json_or_the_raw_arguments():
    title = describe("mystery_tool", payload=[{"a": 1}, {"b": 2}], options={"deep": True}, label="x")

    assert title.startswith("mystery_tool ")
    assert "{" not in title and "}" not in title and '"' not in title
    assert "payload=2 items" in title and "options=1 fields" in title and "label=x" in title
    assert describe("unknown_tool") == "unknown_tool"


def test_the_plan_tool_counts_its_steps():
    assert describe("todo_write", todos=[{"content": "x"}]) == "Updated 1 todo"
    assert describe("todo_write", todos=[{"content": "x"}, {"content": "y"}]) == "Updated 2 todos"
    assert describe("todo_write") == "Updated the plan"


def test_read_rows_name_their_language_and_drop_the_continuation_hint():
    assert DEFAULT_RENDERERS.describe("read_file", {"path": "app.py"}).language == "python"
    assert DEFAULT_RENDERERS.describe("read_file", {"path": "notes.md"}).language is None

    body = DEFAULT_RENDERERS.body("read_file", "one\ntwo\n... [more lines; continue with start_line=3]")

    assert body == "one\ntwo"


def test_the_chain_asks_handlers_in_order():
    class First(ToolHandler):
        """A link that claims one tool to prove the ordering."""

        names = frozenset({"read_file"})

        def describe(self, name: str, arguments: Mapping[str, object]) -> ToolRow:
            return ToolRow("mine")

    chained = Renderers((First(), *DEFAULT_RENDERERS.handlers))

    assert chained.describe("read_file", {}).title == "mine"
    assert chained.describe("write_file", {"path": "x"}).title == "Wrote x"
    # The fallback link claims whatever the ones before it passed over, so an
    # unknown tool still renders as its bare name.
    fallback = next(handler for handler in chained.handlers if isinstance(handler, FallbackTool))
    assert fallback.handles("tool", "anything-at-all")
    assert chained.describe("mystery", {}).title == "mystery"


def test_language_for_path_only_names_real_languages():
    assert language_for_path("src/app.py") == "python"
    assert language_for_path("src/main.rs") == "rust"
    assert language_for_path("Cargo.toml") == "toml"
    assert language_for_path("notes.md") is None
    assert language_for_path("Makefile") is None


def test_the_reasoning_channel_loses_its_provider_wrappers():
    text = DEFAULT_RENDERERS.text

    assert text(THINKING, "<thinking>weighing options</thinking>", opening=True) == "weighing options"
    assert text(THINKING, "still <|thinking|>working", opening=False) == "still working"
    assert text(THINKING, "coloured \x1b[31mred\x1b[0m", opening=False) == "coloured red"
    # A kind no link claims is shown exactly as it arrived.
    assert text("user", "<thinking>kept</thinking>") == "<thinking>kept</thinking>"


def test_a_chat_preamble_is_dropped_only_where_it_can_appear():
    text = DEFAULT_RENDERERS.text

    assert text(ANSWER, "Assistant: here is the fix", opening=True) == "here is the fix"
    assert text(ANSWER, "AI\uff1a \u5df2\u4fee\u590d", opening=True) == "\u5df2\u4fee\u590d"
    # Mid-message the same words are content, not a preamble.
    assert text(ANSWER, "Assistant: the field is unused", opening=False) == "Assistant: the field is unused"
    assert text(ANSWER, "plain \x1b[1mbold\x1b[0m", opening=False) == "plain bold"
