"""The files part: the ``@`` provider and the plugin that registers it."""

from __future__ import annotations

from importlib.metadata import entry_points
from pathlib import Path

from zettcode.engine.plugins.loader import AGENT_PART_GROUP, PLUGIN_ENTRY_POINT_GROUP, part_group
from zettcode.files import FileMentions, FileResources
from zettcode.files.mentions import SKIP_DIRECTORIES


def test_files_are_offered_by_path_and_expanded_to_a_sentence_naming_it(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    files = FileMentions(tmp_path)

    assert [mention.token for mention in files.candidates("app")] == ["@src/app.py"]
    expanded = files.expand("src/app.py")
    assert expanded is not None and "src/app.py" in expanded
    assert files.expand("nothing.py") is None


def test_the_directories_nobody_references_are_not_listed(tmp_path: Path):
    for name in (".git", "node_modules"):
        assert name in SKIP_DIRECTORIES or name.startswith(".")
        (tmp_path / name).mkdir()
        (tmp_path / name / "hidden.txt").write_text("x", encoding="utf-8")

    assert FileMentions(tmp_path).candidates("hidden") == ()


def test_the_plugin_is_a_part_of_the_agent_found_through_its_entry_point_group():
    found = {point.name: point for point in entry_points(group=PLUGIN_ENTRY_POINT_GROUP)}

    assert found["files"].value == "zettcode.files.plugin:FileResources"
    assert part_group(found["files"]) == AGENT_PART_GROUP
    assert FileResources.name == "files" and FileResources.setting is None, "nothing turns it off"
