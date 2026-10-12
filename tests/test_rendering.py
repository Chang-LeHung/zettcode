"""The tool-rendering chain: the words a tool call turns into."""

from __future__ import annotations

from collections.abc import Mapping

from zettcode.app.agent.conversation.rendering import (
    ANSWER,
    DEFAULT_RENDERERS,
    THINKING,
    FallbackTool,
    Renderers,
    ToolHandler,
    ToolRow,
    edited_lines,
    language_for_path,
)


def describe(name: str, **arguments: object) -> str:
    """Return the row title the default chain renders for one call."""
    return row(name, **arguments).title


def row(name: str, **arguments: object) -> ToolRow:
    """Return the whole row the default chain renders for one call."""
    return DEFAULT_RENDERERS.describe(name, arguments)


def test_the_chain_phrases_the_coding_tools():
    assert describe("read_file", path="src/app.py") == "Read src/app.py"
    assert describe("write_file", path="notes/plan.md") == "Wrote notes/plan.md"
    assert describe("replace_in_file", path="app.py", edits=[{"old": "a"}, {"old": "b"}]) == "Edited app.py (2 edits)"
    assert describe("replace_in_file", path="app.py", edits=[{"old": "a"}]) == "Edited app.py (1 edit)"
    assert describe("replace_in_file", path="app.py") == "Edited app.py"
    assert describe("delete_file", path="99\u4e58\u6cd5\u8868.txt") == "Deleted 99\u4e58\u6cd5\u8868.txt"
    assert describe("bash", command="pwd && ls -la") == "Ran pwd && ls -la"
    assert describe("glob", pattern="**/*.py") == "Listed **/*.py"
    assert describe("grep", pattern="TODO", path="src") == "Searched TODO in src"
    # ``name`` is both the helper's parameter and the tool's argument, so this
    # one goes through the chain directly.
    assert DEFAULT_RENDERERS.describe("read_skill", {"name": "code-review"}).title == "Read skill code-review"


def test_an_edit_row_counts_the_lines_it_changes():
    """The row says how large the change is, not only how many edits it carries.

    `Replaced 2 occurrences in app.py` is the tool's whole answer, and it reads the
    same for a two-line fix and a two-hundred-line rewrite. The edits hold both
    texts, so the difference is counted where the tool cannot be asked, and the
    counts ride outside the title because they are drawn in their own colours.
    """
    twelve = "\n".join(f"line {index}" for index in range(12))

    counted = row("replace_in_file", path="app.py", edits=[{"old_text": "a\nb\nc", "new_text": twelve}])

    assert (counted.title, counted.added, counted.removed) == ("Edited app.py (1 edit)", 12, 3)

    # A side stays at zero when nothing was added or removed: the renderer draws
    # nothing for it, so there is no `-0` for a reader to decode.
    added = row("replace_in_file", path="app.py", edits=[{"old_text": "one\ntwo", "new_text": "one\ntwo\nthree"}])
    assert (added.title, added.added, added.removed) == ("Edited app.py (1 edit)", 1, 0)

    removed = row("replace_in_file", path="app.py", edits=[{"old_text": "one\ntwo\nthree", "new_text": "one\nthree"}])
    assert (removed.title, removed.added, removed.removed) == ("Edited app.py (1 edit)", 0, 1)

    both = row(
        "replace_in_file",
        path="app.py",
        edits=[{"old_text": "a", "new_text": "b"}, {"old_text": "c\nd", "new_text": "e"}],
    )
    assert (both.title, both.added, both.removed) == ("Edited app.py (2 edits)", 2, 3)


def test_a_rewritten_line_counts_as_one_added_and_one_removed():
    """The count is the difference, not the difference in length.

    A replacement that keeps the lines around it and changes one of them is one
    line added and one removed; subtracting the lengths would call it nothing.
    """
    rewritten = row(
        "replace_in_file", path="app.py", edits=[{"old_text": "keep\nold\nkeep", "new_text": "keep\nnew\nkeep"}]
    )

    assert (rewritten.title, rewritten.added, rewritten.removed) == ("Edited app.py (1 edit)", 1, 1)


def test_edits_that_carry_no_texts_are_not_guessed_at():
    """An argument shape the counter does not recognise leaves the row as it was."""
    assert describe("replace_in_file", path="app.py", edits=[{"old": "a"}]) == "Edited app.py (1 edit)"
    assert describe("replace_in_file", path="app.py", edits="two edits, honest") == "Edited app.py"


def test_the_counter_ignores_shapes_it_cannot_read():
    """A count is never guessed from a shape the counter does not recognise.

    The arguments arrive from the model, so anything can be in them; a row that
    invented a number would be worse than a row that says less.
    """
    assert edited_lines("two edits, honest") == (0, 0)
    assert edited_lines(None) == (0, 0)
    assert edited_lines([]) == (0, 0)
    assert edited_lines([{"old_text": "a"}, {"new_text": "b"}, "junk", 7]) == (0, 0)
    assert edited_lines([{"old_text": "a", "new_text": "b"}]) == (1, 1)


def test_an_edit_that_replaces_every_occurrence_counts_once():
    """Only the file knows how many matches there are; the row does not guess.

    `replace_all` may hit five occurrences or none, and the arguments cannot say
    which — the tool's answer names the count, and the row counts the edit.
    """
    once = row("replace_in_file", path="app.py", edits=[{"old_text": "old", "new_text": "new", "replace_all": True}])

    assert (once.title, once.added, once.removed) == ("Edited app.py (1 edit)", 1, 1)


def test_a_namespaced_mcp_tool_keeps_its_server_after_the_tool_name():
    assert describe("docs__search", query="fix parser") == "search (via docs) query=fix parser"
    assert describe("search", query="fix parser") == "search query=fix parser"


def test_the_task_tool_reads_as_a_subagent_not_as_raw_arguments():
    assert describe("task", subagent_type="explore", description="survey the project") == (
        "Subagent explore \u00b7 survey the project"
    )
    assert describe("task", subagent_type="explore") == "Subagent explore"
    assert describe("task") == "Subagent (unknown)"
    # The expanded body is the child's report, not the envelope around it.
    report = '{"session_id": "s", "parent_session_id": "p", "subagent_type": "explore", "content": "## Overview"}'
    assert DEFAULT_RENDERERS.body("task", report) == "## Overview"
    assert DEFAULT_RENDERERS.body("task", "not json") == "not json"


def test_a_missing_or_unusable_argument_degrades_to_a_placeholder():
    assert describe("read_file") == "Read (unknown file)"
    assert describe("read_file", path=7) == "Read (unknown file)"
    assert describe("bash", command="   ") == "Ran (unknown command)"
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
