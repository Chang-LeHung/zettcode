"""Plugins name the plugins they need: the order they are activated in, and what happens when a need is not met."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import ClassVar

import pytest

from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.engine.plugins.context import PluginContext
from zettcode.engine.plugins.graph import Node, order
from zettcode.engine.plugins.loader import Loader, RequiredPluginError, load_plugins, run
from zettcode.engine.plugins.plugin import Plugin


def names(*spec: str) -> list[Node]:
    """Return nodes from ``"name:dep,dep"`` strings."""
    nodes = []
    for item in spec:
        name, _, deps = item.partition(":")
        nodes.append(Node(name, tuple(dep for dep in deps.split(",") if dep)))
    return nodes


def test_with_no_edges_the_order_is_the_order_offered():
    ordered, failed = order(names("c", "a", "b"))

    assert ordered == [0, 1, 2]
    assert failed == {}


def test_a_plugin_comes_after_what_it_needs_and_the_rest_keep_their_places():
    nodes = names("app:ui", "x", "ui:core", "core", "y")

    ordered, failed = order(nodes)

    assert [nodes[i].name for i in ordered] == ["x", "core", "ui", "app", "y"]
    assert failed == {}


def test_a_missing_need_fails_the_plugin_and_everything_that_needs_it():
    ordered, failed = order(names("a:ghost", "b:a", "c"))

    assert ordered == [2]
    assert "ghost" in failed[0]
    assert "'a'" in failed[1]


def test_a_cycle_is_named_and_leaves_the_rest_alone():
    nodes = names("a:b", "b:c", "c:a", "d:a", "e")

    ordered, failed = order(nodes)

    assert ordered == [4]
    assert failed[0] == "dependency cycle: a -> b -> c -> a"
    assert set(failed) == {0, 1, 2, 3}
    assert "cycle" in failed[3]


def test_a_plugin_that_lists_itself_is_refused():
    _, failed = order(names("a:a"))

    assert "itself" in failed[0]


class Base(Plugin[PluginContext]):
    seen: ClassVar[list[str]] = []

    def activate(self, container: PluginContext) -> None:
        Base.seen.append(self.name)


def plugin(name: str, *deps: str, broken: bool = False) -> Plugin[PluginContext]:
    class Made(Base):
        def activate(self, container: PluginContext) -> None:
            if broken:
                raise RuntimeError("boom")
            super().activate(container)

    Made.name = name
    Made.deps = deps
    return Made()


class Point:
    """The slice of an entry point the loader touches."""

    def __init__(self, name: str, target: Plugin[PluginContext]) -> None:
        self.name = name
        self._target = target

    def load(self) -> Plugin[PluginContext]:
        return self._target


def config(tmp_path: Path, **changes: object) -> ZettCodeConfig:
    base = ZettCodeConfig(
        workspace=tmp_path,
        models=(ModelConfig(model="gpt", token="t"),),
        plugins_dir=tmp_path / "plugins",
        plugins_file=tmp_path / "off.json",
    )
    return replace(base, **changes)


@pytest.fixture(autouse=True)
def _clear_seen() -> None:
    Base.seen.clear()


def test_the_loader_activates_in_dependency_order(tmp_path: Path):
    points = [Point("a", plugin("a", "b")), Point("b", plugin("b"))]

    bundle = load_plugins(config(tmp_path), builtins=(), entry_points=points)

    assert Base.seen == ["b", "a"]
    assert [p.name for p in bundle.plugins] == ["b", "a"]
    assert bundle.failed == ()


def test_a_disabled_plugin_takes_its_dependents_with_it(tmp_path: Path):
    points = [Point("a", plugin("a", "b")), Point("b", plugin("b"))]

    bundle = load_plugins(config(tmp_path, disabled_plugins=("b",)), builtins=(), entry_points=points)

    assert [p.name for p in bundle.plugins] == []
    assert [origin for origin, _ in bundle.failed] == ["a"]
    assert "'b'" in bundle.failed[0][1]


def test_a_plugin_whose_need_fails_to_activate_is_not_activated(tmp_path: Path):
    points = [Point("a", plugin("a", "b")), Point("b", plugin("b", broken=True))]

    bundle = load_plugins(config(tmp_path), builtins=(), entry_points=points)

    assert Base.seen == []
    assert {origin for origin, _ in bundle.failed} == {"a", "b"}


def test_a_required_plugin_cannot_be_disabled_and_nor_can_what_it_needs(tmp_path: Path, caplog):
    points = [Point("shell", plugin("shell", "rows")), Point("rows", plugin("rows")), Point("extra", plugin("extra"))]
    off = config(tmp_path, disabled_plugins=("shell", "rows", "extra"))

    with caplog.at_level("WARNING", logger="zettcode.plugins"):
        bundle = load_plugins(off, builtins=(), entry_points=points, required=("shell",))

    assert [p.name for p in bundle.plugins] == ["rows", "shell"]
    assert {record.plugin for record in caplog.records if record.getMessage() == "plugins.required"} == {
        "shell",
        "rows",
    }


def test_it_will_not_start_without_a_required_plugin(tmp_path: Path):
    with pytest.raises(RequiredPluginError) as raised:
        load_plugins(config(tmp_path), builtins=(), entry_points=[], required=("presenters",))

    assert raised.value.missing == {"presenters": "not installed"}


def test_it_says_why_a_required_plugin_did_not_load(tmp_path: Path):
    points = [Point("presenters", plugin("presenters", broken=True))]

    with pytest.raises(RequiredPluginError) as raised:
        load_plugins(config(tmp_path), builtins=(), entry_points=points, required=("presenters",))

    assert "boom" in raised.value.missing["presenters"]


def test_a_plugin_finds_what_the_plugin_it_needs_injected(tmp_path: Path):
    found: list[object] = []

    class Maker(Plugin[PluginContext]):
        name = "maker"

        def activate(self, container: PluginContext) -> None:
            container.inject("greeting", "hello")

    class User(Plugin[PluginContext]):
        name = "user"
        deps = ("maker",)

        def activate(self, container: PluginContext) -> None:
            found.append(container.service("greeting", str))

    points = [Point("user", User()), Point("maker", Maker())]

    bundle = load_plugins(config(tmp_path), builtins=(), entry_points=points)

    assert found == ["hello"]
    assert bundle.service("greeting", str) == "hello"


def test_a_second_plugin_with_the_same_name_is_refused(tmp_path: Path):
    points = [Point("one", plugin("same")), Point("two", plugin("same"))]

    bundle = load_plugins(config(tmp_path), builtins=(), entry_points=points)

    assert [p.origin for p in bundle.plugins] == ["one"]
    assert "duplicate plugin name 'same'" in bundle.failed[0][1]


def test_a_plugin_cannot_take_the_entry_point_name_of_a_part_and_so_cannot_stand_in_for_a_required_one(
    tmp_path: Path, caplog
):
    class Impostor(Base):
        name = "presenters"

    part = Point("presenters", plugin("presenters"))
    part.group = "zettcode.terminal"  # type: ignore[attr-defined]
    points = [part, Point("presenters", Impostor())]

    bundle = run(Loader(config(tmp_path)), config(tmp_path), builtins=(), entry_points=points, terminal=True)

    assert [p.__class__ for p in bundle.plugins] == [type(part._target)]
    assert bundle.failed == ()
    assert [name for name, _note in bundle.taken] == ["presenters"]
    assert "already has the name 'presenters'" in bundle.taken[0][1]
    assert [r.plugin for r in caplog.records if r.getMessage() == "plugins.name_taken"] == ["presenters"]


def test_a_part_the_reader_switched_off_is_not_a_clash_with_the_plugin_that_shares_its_name(tmp_path: Path):
    part = Point("pets", plugin("pets"))
    part.group = "zettcode.terminal"  # type: ignore[attr-defined]
    other = Point("pets", plugin("pets"))
    off = config(tmp_path, disabled_plugins=("pets",))

    bundle = run(Loader(off), off, builtins=(), entry_points=[part, other], terminal=True)

    assert bundle.plugins == () and bundle.failed == ()


def test_the_same_distribution_listed_twice_is_one_plugin_and_not_a_failure(tmp_path: Path):
    class Dist:
        def __init__(self, name: str) -> None:
            self.name = name

    first, second = Point("dup", plugin("dup")), Point("dup", plugin("dup"))
    first.dist, second.dist = Dist("Some.Dist"), Dist("some_dist")  # type: ignore[attr-defined]  # one project, PEP 503

    bundle = load_plugins(config(tmp_path), builtins=(), entry_points=[first, second])

    assert [p.name for p in bundle.plugins] == ["dup"] and bundle.failed == ()


def test_a_file_that_shares_a_name_with_an_entry_point_is_reported_like_one(tmp_path: Path):
    from zettcode.engine.plugins import catalog

    folder = tmp_path / "plugins"
    folder.mkdir()
    (folder / "same.py").write_text("from zettcode.engine.plugins import Plugin\nclass Mine(Plugin):\n    pass\n")
    points = [Point("same", plugin("same"))]

    bundle = load_plugins(config(tmp_path), builtins=(), entry_points=points)

    assert [p.name for p in bundle.plugins] == ["same"]
    assert bundle.failed == (), "the plugin that has the name loaded; the file is not a failure of it"
    rows = catalog(config(tmp_path), bundle, entry_points=points)
    assert [(row.origin, row.failure) for row in rows] == [("same", ""), ("same", "")], (
        "the winner's row, and the file's note, neither reading 'could not load'"
    )
    assert "already has the name" in rows[1].note and not rows[1].switchable


def test_a_lost_name_is_a_note_a_list_can_show_not_a_failure(tmp_path: Path):
    from zettcode.engine.plugins import Plugins
    from zettcode.engine.plugins.switches import catalog

    bundle = Plugins(taken=(("presenters", "the file fake.py: presenters already has the name 'presenters'"),))

    rows = catalog(config(tmp_path), bundle, entry_points=())

    row = next(row for row in rows if row.name == "presenters")
    assert row.failure == "" and row.note and not row.switchable
    assert "already has the name" in row.note


def test_an_impostor_is_still_reported_when_the_part_it_imitates_was_disabled_and_pulled_back_in(
    tmp_path: Path, caplog
):
    class Impostor(Base):
        name = "presenters"

    part = Point("presenters", plugin("presenters"))
    part.group = "zettcode.terminal"  # type: ignore[attr-defined]
    off = config(tmp_path, disabled_plugins=("presenters",))

    bundle = run(
        Loader(off),
        off,
        builtins=(),
        entry_points=[part, Point("presenters", Impostor())],
        required=("presenters",),
        terminal=True,
    )

    assert [p.origin for p in bundle.plugins] == ["presenters"]
    assert bundle.failed == (), "the part loaded; the impostor is not a failure of it"
    assert [name for name, _note in bundle.taken] == ["presenters"]
    assert [r.plugin for r in caplog.records if r.getMessage() == "plugins.name_taken"] == ["presenters"]
