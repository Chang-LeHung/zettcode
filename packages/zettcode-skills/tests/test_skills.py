"""The skills part: the ``@`` provider, the plugins, and where a skill stands against a file of the same name."""

from __future__ import annotations

from importlib.metadata import entry_points
from pathlib import Path

from zettcode.config import ZettCodeConfig
from zettcode.engine.plugins.loader import AGENT_PART_GROUP, part_group
from zettcode.mention import Mention, MentionProvider, MentionRegistry
from zettcode.skills import SkillMentions, SkillResources, SkillTool
from zettcode.skills.plugin import PLUGINS


def _skill(root: Path, name: str) -> None:
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {name} skill\n---\n\nBody.\n", encoding="utf-8"
    )


class _Files(MentionProvider):
    """A provider that offers a file with the name a skill has."""

    kind = "file"

    def __init__(self, name: str) -> None:
        self._name = name

    def candidates(self, query: str) -> tuple[Mention, ...]:
        return (Mention(f"@{self._name}", self.kind, self._name, "a file"),)

    def expand(self, name: str) -> str | None:
        return "FILE" if name == self._name else None


def test_a_skill_is_asked_before_a_file_whatever_order_they_were_registered_in(tmp_path: Path):
    _skill(tmp_path, "test")
    skills = SkillMentions((tmp_path,))

    for providers in ([_Files("test"), skills], [skills, _Files("test")]):
        registry = MentionRegistry(providers)

        assert [mention.kind for mention in registry.candidates("te")] == ["skill"]
        expanded = registry.expand_token("@test")
        assert expanded is not None and expanded.startswith('Use the "test" skill')


def test_the_skills_are_offered_by_name_and_an_unknown_one_expands_to_nothing(tmp_path: Path):
    _skill(tmp_path, "review")
    skills = SkillMentions((tmp_path,))

    assert [mention.name for mention in skills.candidates("")] == ["review"]
    assert skills.expand("nothing") is None


def test_both_plugins_are_parts_of_the_agent_found_through_its_entry_point_group():
    found = {
        point.name: point
        for point in entry_points(group=AGENT_PART_GROUP)
        if point.value.startswith("zettcode.skills.")
    }

    assert found["parts"].value == "zettcode.skills.plugin:PLUGINS", "one point for both parts"
    assert part_group(found["parts"]) == AGENT_PART_GROUP, "the program's own, so no `[plugins] disable` reaches it"
    assert [plugin.name for plugin in PLUGINS] == ["skills", "skill-tool"]


def test_the_switch_is_the_skills_setting_and_off_registers_nothing(tmp_path: Path):
    from zettcode.config import ModelConfig

    assert SkillResources.setting is not None and SkillResources.setting.key == "enabled"
    config = ZettCodeConfig(
        workspace=tmp_path,
        store=tmp_path / "store",
        models=(ModelConfig(model="m", token="t"),),
        skills_enabled=False,
    )

    class _Agent:
        def __getattr__(self, name: str):  # any registration is a failure
            raise AssertionError(f"registered {name} with skills off")

    class _Context:
        agent = _Agent()

        def __init__(self) -> None:
            self.config = config

    SkillResources().activate(_Context())  # type: ignore[arg-type]
    SkillTool().activate(_Context())  # type: ignore[arg-type]
