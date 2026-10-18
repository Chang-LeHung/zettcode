"""The language floor: every module has to run on Python 3.10 through 3.14.

CI runs the suite on each version, but syntax only breaks on the oldest one, and
a module no test happens to import would fail there and nowhere else. The check
here reads the tree instead, so the floor breaks a normal local run too.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from zettcode._compat import StrEnum, tomllib

#: The oldest interpreter the package claims, written the way ``ast`` wants it.
FLOOR = (3, 10)

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _sources() -> list[pathlib.Path]:
    """Return every module the tooling reads: the package, the tests, the probes."""
    return sorted(path for folder in ("src", "tests", "perf") for path in (ROOT / folder).rglob("*.py"))


def test_every_module_parses_as_the_oldest_supported_python():
    """A construct the floor cannot read is a SyntaxError there, not a slow path."""
    unreadable: list[str] = []
    for path in _sources():
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path), feature_version=FLOOR)
        except SyntaxError as error:
            unreadable.append(f"{path.relative_to(ROOT)}:{error.lineno}: {error.msg}")

    assert unreadable == []


class Activity(StrEnum):
    """A member the way the application declares one."""

    READY = "ready"


def test_the_str_enum_shim_reads_like_the_value_it_carries():
    """Rows and stored records show ``ready``; a member that str()s as ``Activity.READY`` leaks."""
    assert str(Activity.READY) == "ready"
    assert f"{Activity.READY}" == "ready"
    assert f"{Activity.READY:>7}" == "  ready"
    assert Activity.READY == "ready"
    assert Activity("ready") is Activity.READY


def test_the_toml_reader_parses_what_the_config_and_theme_files_hold():
    """The 3.10 fallback has to accept the same files the stdlib reader accepts."""
    source = '[[models]]\nmodel = "m"\ntoken = "t"\n\n[ui]\naccent = "#a7c080"\n'

    assert tomllib.loads(source) == {
        "models": [{"model": "m", "token": "t"}],
        "ui": {"accent": "#a7c080"},
    }
    with pytest.raises(tomllib.TOMLDecodeError):
        tomllib.loads("model = ")
