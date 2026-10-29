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
    edit_changes,
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
    """`Read app.py` and not how much of it: the count is of what came back, not of the range asked for."""
    from zettcode.app.agent.conversation.entries import EntryStatus

    entry = opened("read", path="app.py")

    DEFAULT_RENDERERS.finished(entry, "line one\nline two\nline three", EntryStatus.COMPLETED)
    assert (entry.title, entry.lines) == ("Read app.py", 3), "the row keeps the title it was opened with"

    one = opened("read_file", path="notes.md")
    DEFAULT_RENDERERS.finished(one, "only line", EntryStatus.COMPLETED)
    assert one.lines == 1, 'one line is not "1 lines" once the presenter writes it'

    failed = opened("read", path="missing.py")
    DEFAULT_RENDERERS.finished(failed, "File does not exist: missing.py", EntryStatus.FAILED)
    assert failed.lines is None, "an error message is not a file that was read"

    picture = opened("read", path="dot.png")
    DEFAULT_RENDERERS.finished(picture, "Image dot.png: image/png, 71 bytes", EntryStatus.COMPLETED)
    assert picture.lines is None, "a picture is not a file of lines"

    prose = opened("read", path="notes.txt")
    DEFAULT_RENDERERS.finished(prose, "Image file formats, and how to pick one\nsecond line", EntryStatus.COMPLETED)
    assert prose.lines == 2, 'a text file whose first line begins with "Image " is still text'


def test_a_read_row_does_not_lose_its_count_when_the_title_is_restated_or_cut():
    """The count is a field of the row, the way an edit's ``+N`` is, so neither can take it away."""
    from zettcode.app import Transcript, TranscriptView
    from zettcode.tui import DARK
    from zettcode.tui.testing import render_block

    transcript = Transcript(clock=lambda: 0.0)
    transcript.start_tool("1", "read", {"path": "a/very/long/path/that/would/push/the/count/off.py"})
    transcript.complete_tool("1", "line one\nline two")
    transcript.restate_tool("1", {"path": "a/long/path/would/push/the/count/off.py"})

    rendered = render_block(TranscriptView(transcript, theme=DARK), width=60, height=8, theme=DARK)
    assert "\u00b7 2 lines" in rendered, rendered


def test_the_chain_phrases_the_coding_tools():
    assert describe("read_file", file_path="src/app.py") == "Read src/app.py"
    assert describe("write_file", file_path="notes/plan.md") == "Write notes/plan.md"
    assert describe("edit", file_path="app.py", old_string="a", new_string="b") == "Edit app.py"
    assert describe("edit", file_path="app.py") == "Edit app.py"
    assert describe("replace_in_file", path="app.py") == "Edit app.py", "a stored session keeps its own argument name"
    assert describe("delete_file", path="99\u4e58\u6cd5\u8868.txt") == "Deleted 99\u4e58\u6cd5\u8868.txt"
    assert describe("bash", command="pwd && ls -la") == "Bash pwd && ls -la"
    assert describe("glob", pattern="**/*.py") == "Listed **/*.py"
    assert describe("grep", pattern="TODO", file_pattern="src") == "Searched TODO in src"
    assert describe("grep", pattern="TODO", path="src") == "Searched TODO in src", "a stored session's argument"
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
    """The row says how large the change is, which the tool's own answer does not.

    `Replaced 1 occurrence in app.py` reads the same for a two-line fix and a
    two-hundred-line rewrite. The call carries both texts, so the difference is
    counted where the tool cannot be asked, and the counts ride outside the title
    because they are drawn in their own colours.
    """
    twelve = "\n".join(f"line {index}" for index in range(12))

    counted = opened("edit", file_path="app.py", old_string="a\nb\nc", new_string=twelve)

    assert (counted.title, counted.added, counted.removed) == ("Edit app.py", 12, 3)

    # A side stays at zero when nothing was added or removed: the renderer draws
    # nothing for it, so there is no `-0` for a reader to decode.
    added = opened("edit", file_path="app.py", old_string="one\ntwo", new_string="one\ntwo\nthree")
    assert (added.title, added.added, added.removed) == ("Edit app.py", 1, 0)

    removed = opened("edit", file_path="app.py", old_string="one\ntwo\nthree", new_string="one\nthree")
    assert (removed.title, removed.added, removed.removed) == ("Edit app.py", 0, 1)


def test_a_rewritten_line_counts_as_one_added_and_one_removed():
    """The count is the difference, not the difference in length.

    A replacement that keeps the lines around it and changes one of them is one
    line added and one removed; subtracting the lengths would call it nothing.
    """
    rewritten = opened("edit", file_path="app.py", old_string="keep\nold\nkeep", new_string="keep\nnew\nkeep")

    assert (rewritten.title, rewritten.added, rewritten.removed) == ("Edit app.py", 1, 1)


def test_a_stored_batch_of_edits_is_still_read():
    """A session written before a call carried one change has a list under ``edits``; it still shows its diff."""
    legacy = opened(
        "replace_in_file",
        path="app.py",
        edits=[{"old_text": "a", "new_text": "b"}, {"old_text": "c\nd", "new_text": "e"}],
    )

    assert (legacy.title, legacy.added, legacy.removed) == ("Edit app.py", 2, 3)
    assert ("@", "edit 1 of 2") in legacy.diff and ("@", "edit 2 of 2") in legacy.diff


def test_edits_that_carry_no_texts_are_not_guessed_at():
    """An argument shape the counter does not recognise leaves the row as it was."""
    assert describe("edit", file_path="app.py", old_string="a") == "Edit app.py"
    assert describe("edit", file_path="app.py", edits="two edits, honest") == "Edit app.py"
    assert edit_changes({"edits": [{"old_text": "a"}]}) == ()


def test_the_counter_ignores_shapes_it_cannot_read():
    """A count is never guessed from a shape the counter does not recognise.

    The arguments arrive from the model, so anything can be in them; a row that
    invented a number would be worse than a row that says less.
    """
    assert edit_changes({"edits": "two edits, honest"}) == ()
    assert edit_changes({"edits": None}) == ()
    assert edit_changes({"edits": []}) == ()
    assert edit_changes({"edits": [{"old_text": "a"}, {"new_text": "b"}, "junk", 7]}) == ()
    assert edit_changes({"old_string": 7, "new_string": "b"}) == ()
    assert edited_lines(edit_changes({"old_string": "a", "new_string": "b"})) == (1, 1)


def test_an_edit_that_replaces_every_occurrence_counts_once():
    """Only the file knows how many matches there are; the row does not guess.

    `replace_all` may hit five occurrences or none, and the arguments cannot say
    which — the tool's answer names the count, and the row counts the change.
    """
    once = opened("edit", file_path="app.py", old_string="old", new_string="new", replace_all=True)

    assert (once.title, once.added, once.removed) == ("Edit app.py", 1, 1)


def test_a_namespaced_tool_names_its_server_without_claiming_a_protocol():
    """The row says what the name says: a plugin's ``a__b`` is namespaced too, so the word cannot be ``MCP``."""
    assert describe("docs__search", query="fix parser") == "docs/search query=fix parser"
    assert describe("my_plugin__helper", x=1) == "my_plugin/helper x=1"
    assert describe("mcp__github__create_issue", title="A bug") == "github/create_issue title=A bug"
    assert describe("mcp__github") == "mcp__github", "a name without a tool part keeps its own name"
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
    assert describe("read_file", file_path=7) == "Read (unknown file)"
    assert describe("bash", command="   ") == "Bash (unknown command)"
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
    assert DEFAULT_RENDERERS.describe("read_file", {"file_path": "app.py"}).language == "python"
    assert DEFAULT_RENDERERS.describe("read_file", {"file_path": "notes.md"}).language is None

    for hint in (
        "... [more lines; continue with offset=3]",
        "... [output truncated; continue with offset=1200]",
        "... [line truncated; line 2 is longer than the 50 KB output limit and was cut here; read it with the shell]",
    ):
        body = DEFAULT_RENDERERS.body("read_file", f"one\ntwo\n{hint}")
        assert body == "one\ntwo", hint


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
