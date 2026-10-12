"""`@` references: providers, expansion, plugin registration, and restore."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest
from zett_agent.messages import UserMessage

from zettcode.app.agent.agent import MentionPart, ZettCodeAgent, mention_hint
from zettcode.app.agent.mentions import (
    LISTING_SECONDS,
    MAX_CANDIDATES,
    MENTION,
    FileMentions,
    Mention,
    MentionProvider,
    MentionRegistry,
    SkillMentions,
)
from zettcode.app.agent.replay import replay
from zettcode.app.agent.storage import SessionStore
from zettcode.app.ui.widgets import Composer
from zettcode.app.ui.widgets.completer import CommandCompleter
from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.plugins import PluginContainer
from zettcode.tui import TextArea

#: What each ``@`` token expands to in the table-driven tests below.
HINTS = {"note": "H", "1": "H1", "2": "H2"}


def _registry() -> MentionRegistry:
    """Return a registry whose ``@note``, ``@1``, and ``@2`` expand to ``H*``."""
    return MentionRegistry([_TextMentions("note", HINTS)])


def _parts(draft: str, *, image: bool = False):
    """Return the prompt parts the composer produces for one draft."""
    composer = Composer()
    composer.set_text(draft)
    if image:
        composer.position = len(composer.text)
        composer.attach_image(b"png", "image/png")
    return composer.parts()


class _TextMentions(MentionProvider):
    """A provider over a fixed name-to-text table, for tests."""

    def __init__(self, kind: str, entries: dict[str, str]) -> None:
        self.kind = kind
        self.entries = entries

    def candidates(self, query: str) -> Sequence[Mention]:
        return tuple(
            Mention(token=f"@{name}", kind=self.kind, name=name, description="")
            for name in self.entries
            if name.startswith(query)
        )

    def expand(self, name: str) -> str | None:
        return self.entries.get(name)


class _Roots:
    """The slice of config a skill provider reads."""

    def __init__(self, roots: Sequence[Path]) -> None:
        self._roots = tuple(roots)

    def skill_search_roots(self) -> tuple[Path, ...]:
        return self._roots


def _write_skill(root: Path, name: str, description: str, body: str) -> None:
    """Write one valid SKILL.md under ``root``."""
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n",
        encoding="utf-8",
    )


def test_the_registry_expands_known_mentions_and_leaves_unknown_ones_alone(tmp_path: Path):
    _write_skill(tmp_path, "code-review", "review a diff", "Check the diff for regressions.")
    registry = MentionRegistry([SkillMentions(_Roots((tmp_path,)))])

    assert [mention.token for mention in registry.candidates("cod")] == ["@code-review"]
    assert [mention.kind for mention in registry.candidates("cod")] == ["skill"]

    expanded = registry.expand_token("@code-review")

    assert expanded is not None
    # The message names the skill; loading its instructions is the model's call.
    assert 'Use the "code-review" skill' in expanded
    assert 'read_skill(name="code-review")' in expanded
    # A skill read earlier in the conversation must not be loaded again.
    assert "not already in context" in expanded
    assert "Check the diff for regressions." not in expanded
    # An unknown token contributes nothing, so the draft is sent as typed.
    assert registry.expand_token("@missing") is None


def test_a_plugin_registers_one_mention_provider_per_kind(tmp_path: Path):
    config = ZettCodeConfig(workspace=tmp_path, models=(ModelConfig(model="m", token="t"),))
    container = PluginContainer(config)
    provider = _TextMentions("note", {"todo": "a note"})

    assert container.register_mention(provider) is provider
    assert container.mentions == (provider,)

    with pytest.raises(ValueError, match="already registered"):
        container.register_mention(_TextMentions("note", {"other": "text"}))
    with pytest.raises(ValueError, match="cannot be empty"):
        container.register_mention(_TextMentions("  ", {}))


def test_the_completer_offers_mentions_after_an_at_sign():
    registry = MentionRegistry([_TextMentions("note", {"todo": "a note", "topic": "another"})])
    completer = CommandCompleter((), registry)

    assert [item.value for item in completer("@to", 3)] == ["@todo", "@topic"]
    # The token is the word under the cursor, so a mention inside a sentence is
    # still completed.
    assert [item.value for item in completer("please @to", 10)] == ["@todo", "@topic"]
    # A space moves on to the message body, so the menu steps aside.
    assert completer("@todo the", 9) == ()


def test_accepting_a_completion_replaces_only_the_token_under_the_cursor():
    textarea = TextArea()
    textarea.set_text("please @no")

    textarea.replace_token("@note", suffix=" ")

    assert textarea.text == "please @note "
    assert textarea.position == len("please @note ")


def test_request_appends_the_hint_and_keeps_the_typed_text():
    resolved = ZettCodeAgent.request(("typed @skill",), hint='Use the "skill" skill.')

    assert isinstance(resolved, UserMessage)
    assert resolved.text == 'typed @skill\n\nUse the "skill" skill.'
    assert resolved.attributes["prompt"] == "typed @skill"
    # A turn with nothing to append stays the plain text it was.
    assert ZettCodeAgent.request(("typed",)) == "typed"


def test_request_appends_the_hint_to_a_turn_that_also_carries_an_image():
    resolved = ZettCodeAgent.request((MentionPart(token="@note"), (b"png", "image/png")), hint="Use the note.")

    assert isinstance(resolved, UserMessage)
    assert [type(part).__name__ for part in resolved.parts] == ["TextContent", "ImageContent", "TextContent"]
    assert resolved.attributes["prompt"] == "@note"


@pytest.mark.parametrize(
    ("draft", "expected"),
    [
        # No reference: the turn is sent exactly as written.
        ("你好，帮我看看这个", "你好，帮我看看这个"),
        # A reference at the end, in the middle, at the start, or alone: the
        # draft stays verbatim and the hint is appended after a blank line.
        ("看看 @note", "看看 @note\n\nH"),
        ("你好 @note 世界", "你好 @note 世界\n\nH"),
        ("@note 看看", "@note 看看\n\nH"),
        ("@note", "@note\n\nH"),
        # Each reference contributes one block, in the order the tokens appear.
        ("你好 @1 世界 @2 asdasd", "你好 @1 世界 @2 asdasd\n\nH1\n\nH2"),
        # An unknown token resolves to nothing, so nothing is appended.
        ("@missing 你好", "@missing 你好"),
    ],
)
def test_the_model_text_keeps_the_draft_and_appends_each_reference(draft: str, expected: str):
    parts = _parts(draft)
    resolved = ZettCodeAgent.request(parts, hint=mention_hint(parts, _registry()))

    assert (resolved if isinstance(resolved, str) else resolved.text) == expected
    if isinstance(resolved, UserMessage):
        # The session and the restored transcript keep what was typed.
        assert resolved.attributes["prompt"] == draft


def test_a_draft_with_no_provider_is_sent_as_written():
    parts = _parts("@note 看看")

    resolved = ZettCodeAgent.request(parts, hint=mention_hint(parts, MentionRegistry(())))

    assert resolved == "@note 看看"


def test_an_image_turn_appends_the_hint_as_one_more_text_part():
    parts = _parts("看看 @note", image=True)

    resolved = ZettCodeAgent.request(parts, hint=mention_hint(parts, _registry()))

    assert isinstance(resolved, UserMessage)
    assert [type(part).__name__ for part in resolved.parts] == [
        "TextContent",
        "TextContent",
        "TextContent",
        "ImageContent",
        "TextContent",
    ]
    assert resolved.parts[-1].text == "H"
    assert resolved.attributes["prompt"] == "看看 @note[image #1]"


def test_an_image_turn_without_a_reference_carries_no_hint():
    parts = _parts("看看", image=True)

    resolved = ZettCodeAgent.request(parts, hint=mention_hint(parts, _registry()))

    assert isinstance(resolved, UserMessage)
    assert [type(part).__name__ for part in resolved.parts] == ["TextContent", "ImageContent"]
    assert resolved.attributes == {}


def test_an_image_turn_with_an_unknown_reference_is_sent_as_written():
    parts = _parts("@missing", image=True)

    resolved = ZettCodeAgent.request(parts, hint=mention_hint(parts, _registry()))

    assert isinstance(resolved, UserMessage)
    assert [type(part).__name__ for part in resolved.parts] == ["TextContent", "TextContent", "ImageContent"]
    assert resolved.attributes == {}


async def test_replay_shows_the_typed_text_instead_of_the_expanded_one(tmp_path: Path):
    store = SessionStore(tmp_path)
    await store.append(
        "s",
        "req",
        UserMessage(content="expanded @skill", attributes={"prompt": "typed @skill"}),
    )

    replayed = replay(store.read("s"))

    users = [entry.text for entry in replayed.transcript.entries if entry.kind == "user"]
    assert users == ["typed @skill"]
    # The model's history still carries what it was actually sent.
    assert replayed.history[0].text == "expanded @skill"


# -- files in the workspace as @ resources ---------------------------------------


def _write(path: Path, text: str) -> None:
    """Write a file whose size the test will assert, byte for byte.

    ``Path.write_text`` translates ``\\n`` to ``\\r\\n`` on Windows, so a file written
    with it is a byte longer per line there and a size read back differs by platform.
    The menu reports what ``stat`` says, which is what a reader would see, so the
    files have to be exactly what the test thinks they are.
    """
    path.write_bytes(text.encode("utf-8"))


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Return a small tree, with the directories a listing skips filled in."""
    (tmp_path / "src" / "app").mkdir(parents=True)
    _write(tmp_path / "src" / "app" / "cli.py", "print('cli')\n" * 20)
    _write(tmp_path / "src" / "app" / "server.py", "x = 1\n")
    (tmp_path / "tests").mkdir()
    _write(tmp_path / "tests" / "test_cli.py", "assert True\n")
    _write(tmp_path / "README.md", "# readme\n")
    (tmp_path / ".git").mkdir()
    _write(tmp_path / ".git" / "config", "[core]\n")
    (tmp_path / "node_modules" / "left-pad").mkdir(parents=True)
    _write(tmp_path / "node_modules" / "left-pad" / "index.js", "module.exports = 1\n")
    (tmp_path / "__pycache__").mkdir()
    _write(tmp_path / "__pycache__" / "cli.cpython-314.pyc", "\x00")
    return tmp_path


def _files(workspace: Path, *, clock=None) -> FileMentions:
    return FileMentions(workspace) if clock is None else FileMentions(workspace, clock=clock)


def test_a_file_token_is_a_path_and_an_email_is_still_not_a_mention():
    """A draft points at a file by path, so the token holds the punctuation a path does."""
    assert MentionPart("@src/app/cli.py") in _parts("look at @src/app/cli.py")
    assert [match.group(1) for match in MENTION.finditer("see @src/app/cli.py and @README.md")] == [
        "src/app/cli.py",
        "README.md",
    ]
    assert MENTION.findall("mail me at someone@example.com") == []
    assert MENTION.findall("@ @/ @-x") == []
    assert MENTION.findall("@Code-Review_v2 @a/b") == ["Code-Review_v2", "a/b"]


def test_the_workspace_is_offered_without_its_ignored_directories(workspace: Path):
    files = _files(workspace).candidates("")

    paths = [mention.name for mention in files]
    assert paths == sorted(paths, key=lambda path: (len(path), path)) or "src/app/cli.py" in paths
    assert {"README.md", "src/app/cli.py", "src/app/server.py", "tests/test_cli.py"} <= set(paths)
    assert not [path for path in paths if path.startswith((".git/", "__pycache__/", "node_modules/"))]


def test_a_path_that_starts_with_the_query_is_offered_before_one_that_contains_it(workspace: Path):
    files = [mention.name for mention in _files(workspace).candidates("cli")]
    server = [mention.name for mention in _files(workspace).candidates("server")]

    assert files[0] == "src/app/cli.py", "the file named cli.py comes first"
    assert "tests/test_cli.py" in files, "and one that only contains it is still offered"
    assert server == ["src/app/server.py"]
    assert _files(workspace).candidates("nothing-like-this") == ()


def test_the_menu_line_says_how_big_the_file_is(workspace: Path):
    described = {mention.name: mention.description for mention in _files(workspace).candidates("")}

    assert described["src/app/server.py"] == "6 B"
    assert described["README.md"] == "9 B"
    assert described["src/app/cli.py"].endswith(" B")


def test_a_listing_is_reused_and_then_taken_again(workspace: Path):
    """Typing a path must not walk the tree on every keystroke, and a new file must still appear."""
    now = [0.0]
    files = _files(workspace, clock=lambda: now[0])
    assert [mention.name for mention in files.candidates("added")] == []

    (workspace / "added.py").write_text("x = 1\n")
    now[0] = LISTING_SECONDS / 2
    assert [mention.name for mention in files.candidates("added")] == [], "too soon: the listing is reused"

    now[0] = LISTING_SECONDS + 0.1
    assert [mention.name for mention in files.candidates("added")] == ["added.py"]


def test_a_file_deleted_after_the_listing_drops_out_of_the_menu(workspace: Path):
    files = _files(workspace)
    assert [mention.name for mention in files.candidates("server")] == ["src/app/server.py"]

    (workspace / "src" / "app" / "server.py").unlink()

    assert files.candidates("server") == ()


def test_at_most_a_screenful_of_files_is_offered(workspace: Path):
    for index in range(MAX_CANDIDATES + 25):
        (workspace / f"many_{index:03d}.py").write_text("x = 1\n")

    offered = _files(workspace).candidates("many_")

    assert len(offered) == MAX_CANDIDATES


def test_one_token_expands_to_a_sentence_about_the_file_not_its_contents(workspace: Path):
    files = _files(workspace)

    text = files.expand("src/app/cli.py")

    assert text is not None and '"src/app/cli.py"' in text and "read_file" not in text
    assert "print(" not in text, "the body is not inlined: the model has a tool for that"
    assert files.expand("src") is not None and "directory" in (files.expand("src") or "")
    assert files.expand("src/missing.py") is None


def test_a_file_reference_reaches_the_model_as_the_sentence(workspace: Path):
    """The draft is stored as typed; the expansion rides as an attribute, as skills do."""
    registry = MentionRegistry([_files(workspace), _TextMentions("note", HINTS)])

    hint = mention_hint(_parts("what does @src/app/cli.py do, @note?"), registry)

    assert hint is not None
    assert '"src/app/cli.py"' in hint and hint.endswith(HINTS["note"])


def test_the_workspace_offers_files_through_the_builtin_bundle(tmp_path: Path):
    """The shell merges whatever the bundle holds, so the provider has to be in it."""
    from zettcode.plugins import load_plugins

    config = ZettCodeConfig(
        workspace=tmp_path,
        models=(ModelConfig(model="m", token="t"),),
        store=tmp_path / "s",
        skills_enabled=False,
        mcp_enabled=False,
    )
    (tmp_path / "solo.py").write_text("x = 1\n")

    plugins = load_plugins(config, entry_points=())
    registry = MentionRegistry(plugins.mentions)

    assert "solo.py" in [mention.name for mention in registry.candidates("solo")]
    assert "@solo.py" in [mention.token for mention in registry.candidates("solo")]


def test_a_skill_and_a_file_of_the_same_name_are_both_offered_without_duplicating(tmp_path: Path):
    class Skillish(_TextMentions):
        kind = "skill"

    class Fileish(_TextMentions):
        kind = "file"

    registry = MentionRegistry(
        [Skillish("skill", {"README.md": "skill text"}), Fileish("file", {"README.md": "file text"})]
    )

    offered = registry.candidates("README")

    assert [mention.kind for mention in offered] == ["skill"], "the earlier provider owns the name"
    assert registry.expand_token("@README.md") == "skill text"


def test_each_provider_is_asked_for_the_query_rather_than_handed_everything(workspace: Path):
    """Completion runs per keystroke; a provider with thousands of names must not be materialized."""
    asked: list[str] = []

    class Counting(_TextMentions):
        kind = "file"

        def candidates(self, query: str) -> Sequence[Mention]:
            asked.append(query)
            return super().candidates(query)

    registry = MentionRegistry([Counting("file", {"src/app/cli.py": "x", "README.md": "y"})])
    registry.candidates("src")

    assert asked == ["src"]


def test_the_menu_offers_a_path_while_it_is_being_typed(workspace: Path):
    """The composer's completer is what the reader sees, so a typed path has to reach it."""
    registry = MentionRegistry([_files(workspace)])
    completer = CommandCompleter((), registry)
    draft = "look at @src/app/cl"

    items = completer(draft, len(draft))

    assert [item.value for item in items] == ["@src/app/cli.py"]
    assert [item.type for item in items] == ["file"]
