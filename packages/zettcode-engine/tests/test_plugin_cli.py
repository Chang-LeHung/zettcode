"""The command-line options a plugin declares, and the values handed to it."""

from __future__ import annotations

import argparse

from zettcode.engine.plugins.cli import CliOption, add_options, installed_options, values
from zettcode.engine.plugins.plugin import Plugin


class Example(Plugin):
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


def test_a_colliding_or_non_json_option_is_skipped_with_one_line(capsys):
    parser = argparse.ArgumentParser()
    parser.add_argument("--depth")

    assert add_options(parser, [("example", CliOption(("--depth",), "depth"))]) == ()
    assert add_options(parser, [("example", CliOption(("--where",), "where", default=object()))]) == ()
    assert add_options(parser, [("example", CliOption((), "where"))]) == ()
    assert add_options(parser, [("example", CliOption(("--x",), 5))]) == ()
    err = capsys.readouterr().err
    assert "ignored example --depth" in err and "ignored example --where" in err
