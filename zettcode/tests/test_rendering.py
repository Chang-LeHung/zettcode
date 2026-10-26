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


def opened(name: str, **arguments: object):
    """Return the entry the default chain opens for one call: the class that carries what its row shows."""
    return DEFAULT_RENDERERS.open_tool(name, arguments, id=1, call_id="call-1", started_at=0.0)


def test_a_read_row_says_how_many_lines_came_back():
    """`Read app.py` and not how much of it: the count is of what the row shows, not of what was asked for."""
    entry = opened("read", path="app.py")

    DEFAULT_RENDERERS.finished(entry, "line one\nline two\nline three")
    assert entry.title == "Read app.py \u00b7 3 lines"

    one = opened("read_file", path="notes.md")
    DEFAULT_RENDERERS.finished(one, "only line")
    assert one.title == "Read notes.md \u00b7 1 line", 'one line is not "1 lines"'

    picture = opened("read", path="dot.png")
    DEFAULT_RENDERERS.finished(picture, "Image dot.png: image/png, 71 bytes")
    assert picture.title == "Read dot.png", "a picture is not a file of lines"


def test_the_chain_phrases_the_coding_tools():
    assert describe("read_file", path="src/app.py") == "Read src/app.py"
    assert describe("write_file", path="notes/plan.md") == "Write notes/plan.md"
    assert describe("replace_in_file", path="app.py", edits=[{"old": "a"}, {"old": "b"}]) == "Edited app.py (2 edits)"
    assert describe("replace_in_file", path="app.py", edits=[{"old": "a"}]) == "Edited app.py (1 edit)"
    assert describe("replace_in_file", path="app.py") == "Edited app.py"
    assert describe("delete_file", path="99\u4e58\u6cd5\u8868.txt") == "Deleted 99\u4e58\u6cd5\u8868.txt"
    assert describe("bash", command="pwd && ls -la") == "Ran pwd && ls -la"
    assert describe("glob", pattern="**/*.py") == "Listed **/*.py"
    assert describe("grep", pattern="TODO", path="src") == "Searched TODO in src"
    assert describe("web_search", query="zettcode github") == 'Searched the web for "zettcode github"'
    assert describe("web_search") == "Searched the web"
    # A question is the one row that waited for a person: it is named as a thing, with a capital.
    assert describe("ask_user", question="which file?") == "Ask-User: which file?"
    assert describe("ask_user") == "Ask-User"
    assert describe("ask_user", question="  ") == "Ask-User"
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

    counted = opened("replace_in_file", path="app.py", edits=[{"old_text": "a\nb\nc", "new_text": twelve}])

    assert (counted.title, counted.added, counted.removed) == ("Edited app.py (1 edit)", 12, 3)

    # A side stays at zero when nothing was added or removed: the renderer draws
    # nothing for it, so there is no `-0` for a reader to decode.
    added = opened("replace_in_file", path="app.py", edits=[{"old_text": "one\ntwo", "new_text": "one\ntwo\nthree"}])
    assert (added.title, added.added, added.removed) == ("Edited app.py (1 edit)", 1, 0)

    removed = opened(
        "replace_in_file", path="app.py", edits=[{"old_text": "one\ntwo\nthree", "new_text": "one\nthree"}]
    )
    assert (removed.title, removed.added, removed.removed) == ("Edited app.py (1 edit)", 0, 1)

    both = opened(
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
    rewritten = opened(
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
    once = opened("replace_in_file", path="app.py", edits=[{"old_text": "old", "new_text": "new", "replace_all": True}])

    assert (once.title, once.added, once.removed) == ("Edited app.py (1 edit)", 1, 1)


def test_a_namespaced_mcp_tool_names_its_server_before_the_tool():
    assert describe("docs__search", query="fix parser") == "MCP docs/search query=fix parser"
    assert describe("mcp__github__create_issue", title="A bug") == "MCP github/create_issue title=A bug"
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
    assert chained.describe("write_file", {"path": "x"}).title == "Write x"
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


# -- which entry a call opens -----------------------------------------------------------------------------------


def test_each_family_of_tool_opens_the_entry_that_carries_what_its_row_shows():
    from zettcode.app.agent.conversation.entries import DeleteEntry, EditEntry, ReadEntry, ToolEntry, WriteEntry

    kinds = {
        "read_file": (ReadEntry, {"path": "a.py"}),
        "write_file": (WriteEntry, {"path": "a.py", "content": "x"}),
        "replace_in_file": (EditEntry, {"path": "a.py", "edits": []}),
        "bash": (ToolEntry, {"command": "ls"}),
        "grep": (ToolEntry, {"pattern": "x"}),
        "delete_file": (DeleteEntry, {"path": "a.py"}),
        "something_new": (ToolEntry, {}),
    }
    for name, (expected, arguments) in kinds.items():
        assert type(opened(name, **arguments)) is expected, name


def test_an_entry_opens_with_the_words_the_row_gives_it_and_the_identity_it_was_asked_for():
    entry = DEFAULT_RENDERERS.open_tool("read_file", {"path": "src/app.py"}, id=7, call_id="call-9", started_at=3.5)

    assert (entry.id, entry.call_id, entry.tool, entry.title, entry.started_at) == (
        7, "call-9", "read_file", "Read src/app.py", 3.5,
    )  # fmt: skip
    assert entry.language == "python" and entry.running


def test_a_chain_with_no_link_for_a_tool_still_opens_a_plain_entry():
    from zettcode.app.agent.conversation.entries import ToolEntry

    entry = Renderers(()).open_tool("mystery", {"x": 1}, id=1, call_id="c", started_at=0.0)

    assert type(entry) is ToolEntry and entry.title == "mystery"


def test_a_link_that_only_describes_its_tool_gets_a_plain_entry_with_those_words():
    """What a plugin's handler does today: it returns a row, and nothing else has to change."""
    from zettcode.app.agent.conversation.entries import ToolEntry

    class Mine(ToolHandler):
        names = frozenset({"mine"})

        def describe(self, name, arguments):
            return ToolRow("Did mine")

    entry = Renderers((Mine(),)).open_tool("mine", {}, id=1, call_id="c", started_at=0.0)

    assert type(entry) is ToolEntry and entry.title == "Did mine"


def test_a_link_can_open_an_entry_class_of_its_own():
    from dataclasses import dataclass

    from zettcode.app.agent.conversation.entries import ToolEntry

    @dataclass(slots=True, kw_only=True)
    class Deploy(ToolEntry):
        target: str = ""

    class Mine(ToolHandler):
        names = frozenset({"deploy"})

        def open_tool(self, name, arguments, *, id, call_id, started_at):
            return Deploy(
                id=id, call_id=call_id, tool=name, title="Deploy", target=str(arguments["to"]), started_at=started_at
            )

    entry = Renderers((Mine(),)).open_tool("deploy", {"to": "prod"}, id=1, call_id="c", started_at=0.0)

    assert isinstance(entry, Deploy) and entry.target == "prod"


def test_the_transcript_opens_every_row_the_same_way_and_the_handler_picks_the_class():
    from zettcode.app.agent.conversation.entries import EditEntry, ReadEntry, ToolEntry
    from zettcode.app.agent.conversation.transcript import Transcript

    transcript = Transcript(clock=lambda: 0.0)
    transcript.begin_turn("go")
    transcript.start_tool("c1", "read_file", {"path": "a.py"})
    transcript.start_tool("c2", "replace_in_file", {"path": "a.py", "edits": [{"old_text": "a", "new_text": "b"}]})
    transcript.start_tool("c3", "bash", {"command": "ls"})

    tools = [e for e in transcript.entries if isinstance(e, ToolEntry)]

    assert [type(e) for e in tools] == [ReadEntry, EditEntry, ToolEntry]
    assert [e.call_id for e in tools] == ["c1", "c2", "c3"] and all(e.running for e in tools)
