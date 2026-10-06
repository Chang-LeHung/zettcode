"""`@` references: providers, expansion, plugin registration, and restore."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest
from zett_agent.messages import UserMessage

from zettcode.app.agent.agent import MentionPart, ZettCodeAgent, mention_hint
from zettcode.app.agent.mentions import Mention, MentionProvider, MentionRegistry, SkillMentions
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
