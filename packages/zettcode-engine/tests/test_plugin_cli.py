"""The command-line options a plugin declares, and the values handed to it."""

from __future__ import annotations

import argparse

from zettcode.engine.plugins.cli import ENV, CliOption, add_options, from_env, installed_options, to_env, values


class Example:
    """A plugin class as an entry point returns it: the declaration is read, never an instance."""

    @classmethod
    def cli_arguments(cls) -> tuple[CliOption, ...]:
        return (CliOption(("--example-depth",), "depth", default="2", metavar="N"),)


class Point:
    def __init__(self, name: str, target: type) -> None:
        self.name = name
        self._target = target

    def load(self) -> type:
        return self._target


def test_options_are_read_from_the_class_and_parsed_under_the_plugin_name():
    point = Point("example", Example)

    found = installed_options([point])  # type: ignore[list-item]
    parser = argparse.ArgumentParser()
    added = add_options(parser, found)

    assert found[0][0] == "example" and found[0][1].dest == "depth"
    assert values(parser.parse_args(["--example-depth", "7"]), added) == {"example": {"depth": "7"}}


def test_plugin_values_cross_the_daemon_environment(monkeypatch):
    monkeypatch.setenv(ENV, to_env({"example": {"depth": 3}}))

    assert from_env() == {"example": {"depth": 3}}

    monkeypatch.setenv(ENV, "not json")
    assert from_env() == {}
