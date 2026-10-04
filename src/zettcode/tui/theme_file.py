"""Load a theme palette from TOML so colours do not have to be edited in code."""

from __future__ import annotations

import tomllib
from dataclasses import fields, replace
from pathlib import Path

from .core.theme import DARK, Theme, theme_named
from .render.code import CodeTheme
from .render.color import parse_hex

EXAMPLE = """\
base = "dark"                 # dark | light

[ui]
accent = "#a7c080"
error = "#e67e80"

[code]
keyword = "#e58fa8"
string = "#9bddad"
comment = "#6d7a70"
number = "#d8b46a"
function = "#7fb7d8"
builtin = "#b8a6e0"
inline = "#9bddad"
"""


class ThemeFileError(ValueError):
    """Raised when a theme file cannot be understood."""


def theme_from_toml(text: str, *, base: Theme | None = None) -> Theme:
    """Build a theme from TOML text, starting from its base palette.

    Args:
        text: TOML source; ``base`` selects ``dark`` or ``light`` and the ``ui``
            and ``code`` tables override individual roles, so a file only names
            the colours it wants to change.
        base: Palette to override directly; when omitted the file's ``base`` key
            (default ``dark``) is resolved through ``theme_named``.
    """
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ThemeFileError(f"Invalid theme file: {error}") from error
    if not isinstance(data, dict):
        raise ThemeFileError("Theme file must be a table")

    palette = base
    if palette is None:
        requested = data.get("base", DARK.name)
        try:
            palette = theme_named(str(requested))
        except ValueError as error:
            raise ThemeFileError(str(error)) from error

    ui = _select(data.get("ui", {}), {field.name for field in fields(Theme)} - {"code"})
    code = _select(data.get("code", {}), {field.name for field in fields(CodeTheme)})
    return replace(palette, **ui, code=replace(palette.code, **code))


def load_theme(path: Path, *, base: Theme | None = None) -> Theme:
    """Read a theme file from disk.

    Args:
        path: File to read; a missing or unreadable file raises
            ``ThemeFileError`` rather than an ``OSError``.
        base: Palette to override directly, bypassing the file's ``base`` key.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ThemeFileError(f"Cannot read {path}: {error}") from error
    return theme_from_toml(text, base=base)


def _select(values: object, allowed: set[str]) -> dict[str, str]:
    """Validate one palette table against the keys the theme knows."""
    if not isinstance(values, dict):
        raise ThemeFileError("Palette sections must be tables")
    chosen: dict[str, str] = {}
    for key, value in values.items():
        if key not in allowed:
            raise ThemeFileError(f"Unknown theme key: {key!r}")
        if not isinstance(value, str):
            raise ThemeFileError(f"{key} must be a string colour")
        if key != "name" and parse_hex(value) is None:
            raise ThemeFileError(f"{key} must be a #rrggbb colour, got {value!r}")
        chosen[str(key)] = value
    return chosen
