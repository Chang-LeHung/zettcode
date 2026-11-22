"""Explicit inherited backends never disappear silently at plugin load."""

from __future__ import annotations

import math
from dataclasses import FrozenInstanceError
from importlib.metadata import EntryPoint

import pytest
from zett_agent.extensions.base import AgentExtension

from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.engine.plugins import CHILD_STATE, ChildSession, Plugin, PluginContext, load_plugins
from zettcode.engine.plugins.children import decode_child_state, validate_child_state


def config(tmp_path, **changes):
    return ZettCodeConfig(
        workspace=tmp_path, store=tmp_path / "store", models=(ModelConfig(model="m", token="t"),), **changes
    )


def test_child_contract_defaults_and_public_identity():
    from zettcode.plugin_api import CHILD_STATE as public_key
    from zettcode.plugin_api import ChildSession as PublicChild

    child = ChildSession("subagent", "explore")
    assert public_key == CHILD_STATE == "plugin_child_state" and PublicChild is ChildSession
    assert Plugin().export_child(child) is None
    assert Plugin().restore_child({}) is None
    assert Plugin().child_extensions(child) == ()
    with pytest.raises(FrozenInstanceError):
        child.profile = "coding"


def test_restore_precedes_activate_and_export_is_an_isolated_snapshot(tmp_path):
    events = []

    class Backend(Plugin[PluginContext]):
        name = "backend"

        def restore_child(self, state):
            events.append("restore")
            self.state = state

        def activate(self, ctx):
            events.append("activate")
            assert self.state == {"target": {"host": "remote"}}
            assert ctx.service(CHILD_STATE, dict)[self.name] == self.state

        def export_child(self, child):
            assert child == ChildSession("daemon")
            return self.state

    original = {"backend": {"target": {"host": "remote"}}}
    bundle = load_plugins(config(tmp_path), builtins=[Backend], entry_points=(), shared={CHILD_STATE: original})
    snapshot = bundle.export_child(ChildSession("daemon"))
    snapshot["backend"]["target"]["host"] = "changed"
    assert events == ["restore", "activate"]
    assert original["backend"]["target"]["host"] == "remote"
    assert bundle.export_child(ChildSession("daemon")) == original


@pytest.mark.parametrize("failure", ["missing", "restore", "activate", "clash"])
def test_inherited_plugin_missing_or_failed_is_fatal(tmp_path, failure):
    class Backend(Plugin[PluginContext]):
        name = "backend"

        def restore_child(self, state):
            if failure == "restore":
                raise ValueError("bad target")

        def activate(self, ctx):
            if failure == "activate":
                raise ValueError("not available")
            if failure == "clash":
                extension = AgentExtension()
                extension.name = "plugins"
                ctx.agent.register_extension(extension)

    with pytest.raises(ValueError, match="Cannot inherit.*backend"):
        load_plugins(
            config(tmp_path),
            builtins=[] if failure == "missing" else [Backend],
            entry_points=(),
            shared={CHILD_STATE: {"backend": {}}},
        )


def test_disabled_inherited_plugin_is_not_silently_reenabled(tmp_path, monkeypatch):
    class Backend(Plugin[PluginContext]):
        name = "backend"

    point = EntryPoint(name="backend", value="unused:Backend", group="zettcode.plugin")
    monkeypatch.setattr(EntryPoint, "load", lambda self: Backend)
    with pytest.raises(ValueError, match="Cannot inherit.*backend"):
        load_plugins(
            config(tmp_path, disabled_plugins=("backend",)), entry_points=[point], shared={CHILD_STATE: {"backend": {}}}
        )


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        {"": {}},
        {"p": []},
        {"p": {1: "x"}},
        {"p": {"x": object()}},
        {"p": {"x": (1,)}},
        {"p": {"x": math.nan}},
        {"p": {"x": math.inf}},
    ],
)
def test_malformed_state_is_refused_not_dropped(value):
    with pytest.raises(ValueError):
        validate_child_state(value)


@pytest.mark.parametrize(
    "raw", ["", "null", "[]", '{"p":{}} trailing', '{"p":{},"p":{}}', '{"p":{"x":1,"x":2}}', '{"p":{"x":NaN}}']
)
def test_malformed_json_handoff_is_refused(raw):
    with pytest.raises(ValueError):
        decode_child_state(raw)


def test_a_snapshot_a_daemon_cannot_inherit_names_the_plugin_or_the_set(tmp_path):
    class NotJson(Plugin[PluginContext]):
        name = "not-json"

        def export_child(self, child):
            return {"target": object()}

    class NineKib(Plugin[PluginContext]):
        """Under the limit on its own; two of these together are over it."""

        name = "nine-kib"

        def export_child(self, child):
            return {"blob": "x" * (9 * 1024)}

    class AlsoNineKib(NineKib):
        name = "also-nine-kib"

        def export_child(self, child):
            return {"blob": "y" * (9 * 1024)}

    class Fine(Plugin[PluginContext]):
        name = "fine"

        def export_child(self, child):
            return {"target": {"host": "remote"}}

    with pytest.raises(ValueError, match="'not-json'.*cannot inherit"):
        load_plugins(config(tmp_path), builtins=[NotJson, Fine], entry_points=()).export_child(ChildSession("daemon"))
    with pytest.raises(ValueError, match="combined child state cannot be inherited \\(also-nine-kib, nine-kib"):
        load_plugins(config(tmp_path), builtins=[NineKib, AlsoNineKib], entry_points=()).export_child(
            ChildSession("daemon")
        )


def test_inherited_default_off_plugin_is_selected_but_restored_by_name_not_origin(tmp_path, monkeypatch):
    class Backend(Plugin[PluginContext]):
        name = "backend"

        @classmethod
        def default_enabled(cls):
            return False

        def restore_child(self, state):
            self.target = state["target"]

        def activate(self, ctx):
            assert self.target == "remote"

    point = EntryPoint(name="different-origin", value="unused:Backend", group="zettcode.plugin")
    monkeypatch.setattr(EntryPoint, "load", lambda self: Backend)
    bundle = load_plugins(
        config(tmp_path), entry_points=[point], shared={CHILD_STATE: {"backend": {"target": "remote"}}}
    )
    assert bundle.failures == () and bundle.plugins[0].name == "backend"


def test_cyclic_export_is_refused():
    table = {}
    table["self"] = table
    with pytest.raises(ValueError, match="acyclic"):
        validate_child_state({"backend": table})


def test_duplicate_child_extension_names_are_refused(tmp_path):
    class Backend(Plugin[PluginContext]):
        name = "backend"

        def child_extensions(self, child):
            return (AgentExtension(), AgentExtension())

    bundle = load_plugins(config(tmp_path), builtins=[Backend], entry_points=())
    with pytest.raises(ValueError, match="duplicate child extension"):
        bundle.child_extensions(ChildSession("subagent", "coding"))


def test_handoff_has_explicit_serialized_byte_bound():
    from zettcode.engine.plugins.children import MAX_HANDOFF_BYTES, encode_child_state

    assert len(encode_child_state({"backend": {"target": "x" * 100}}).encode("utf-8")) < MAX_HANDOFF_BYTES
    for state in ({"backend": {"target": "x" * MAX_HANDOFF_BYTES}}, {"backend": {"target": "中" * 4000}}):
        with pytest.raises(ValueError, match="16 KiB"):
            encode_child_state(state)
    with pytest.raises(ValueError, match="16 KiB"):
        decode_child_state(" " * MAX_HANDOFF_BYTES + "{}")
