"""Load a theme palette from TOML so colours do not have to be edited in code.

A palette is a file, and a palette's name is the file's name. The ones that ship with the program are TOML files in
``themes/`` beside this module, and the reader's own are ``<name>.toml`` files in a directory of theirs
(``~/.zettcode/themes``); both are read by the same code, so adding a palette is writing one file and nothing else.
Only the *names* are listed up front (a directory listing); a palette's file is read when it is asked for, so a
start pays for no palette it does not use.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, fields, replace
from functools import partial
from importlib import resources
from pathlib import Path

from .._compat import tomllib
from .core.theme import DARK, LIGHT, Theme, ToolTheme, theme_named
from .render.code import CodeTheme
from .render.color import parse_hex

#: The palettes that ship as files, in the order a menu lists them: the dark ones, then the light ones.
BUNDLED = (
    "catppuccin-mocha",
    "tokyo-night",
    "nord",
    "gruvbox-dark",
    "rose-pine",
    "kanagawa",
    "dracula",
    "one-dark",
    "solarized-dark",
    "github-dimmed",
    "ayu-mirage",
    "catppuccin-latte",
    "rose-pine-dawn",
    "gruvbox-light",
    "solarized-light",
    "github-light",
)

#: What a palette's name may be. It is typed after ``/theme`` as one word, so it holds no space.
THEME_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")

#: Names the program reserves: they are what the terminal's own light or dark is mapped to, and a file cannot
#: take them over.
RESERVED_THEMES = (DARK.name, LIGHT.name)

#: The page the two built-in palettes paint when they are chosen by name.
PAGES = {DARK.name: "#232a2e", LIGHT.name: "#f7f8f5"}

EXAMPLE = """\
base = "dark"                 # dark | light
description = "my palette"    # shown beside its name in the /theme menu

[ui]
accent = "#a7c080"
error = "#e67e80"
# diff_added = "#a7c080"       # default: the accent
# diff_removed = "#e67e80"     # default: the error colour
surface_side = "#393a44"
surface_peer = "#313244"

[tools]
read = "#89b4fa"
shell = "#fab387"

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
        text: TOML source; ``base`` selects ``dark`` or ``light`` and the ``ui``,
            ``tools``, and ``code`` tables override individual roles, so a file
            only names the colours it wants to change.
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

    ui = _select(data.get("ui", {}), {field.name for field in fields(Theme)} - {"code", "tools"})
    tools = _select(data.get("tools", {}), {field.name for field in fields(ToolTheme)})
    code = _select(data.get("code", {}), {field.name for field in fields(CodeTheme)})
    return replace(palette, **ui, tools=replace(palette.tools, **tools), code=replace(palette.code, **code))


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


@dataclass(frozen=True, slots=True)
class ThemeSource:
    """A palette that something offers by name: the program's own files, or a plugin.

    Attributes:
        name: What ``/theme`` is typed with; one word.
        load: Builds the palette. Called when it is asked for, never before, so a source costs nothing until picked.
        description: The one-line note the menu shows beside the name, or a function that returns it (called only
            when a menu is opened, for the same reason).
    """

    name: str
    load: Callable[[], Theme]
    description: str | Callable[[], str] = ""


def _bundled_text(name: str) -> str:
    """Return the text of one palette file that ships with the program."""
    return (resources.files(__package__) / "themes" / f"{name}.toml").read_text(encoding="utf-8")


def _load_bundled(name: str) -> Theme:
    return theme_from_toml(_bundled_text(name))


def _bundled_note(name: str) -> str:
    note = tomllib.loads(_bundled_text(name)).get("description")
    return note if isinstance(note, str) else ""


def _file_note(path: Path) -> str:
    note = tomllib.loads(path.read_text(encoding="utf-8")).get("description")
    return note if isinstance(note, str) else ""


def file_theme(name: str, path: Path) -> ThemeSource:
    """Return a source for a palette kept in a TOML file, read when it is asked for and not before."""
    return ThemeSource(name, partial(load_theme, path), partial(_file_note, path))


def bundled_themes() -> tuple[ThemeSource, ...]:
    """Return the palettes that ship as files, as sources: the built-in plugin registers these.

    Nothing is read here; each file is opened when its palette is asked for, or its note when a menu is.
    """
    return tuple(ThemeSource(name, partial(_load_bundled, name), partial(_bundled_note, name)) for name in BUNDLED)


def _user_file(name: str, directory: Path | None) -> Path | None:
    """Return the reader's file for a palette name, or ``None``. A name that is not one word is never a file."""
    if directory is None or name in RESERVED_THEMES or not THEME_NAME.fullmatch(name):
        return None
    path = directory / f"{name}.toml"
    return path if path.is_file() else None


def _user_names(directory: Path | None) -> tuple[str, ...]:
    """Return the names of the reader's palettes: the ``.toml`` files in their directory, by name."""
    if directory is None:
        return ()
    try:
        stems = sorted(path.stem for path in directory.glob("*.toml") if path.is_file())
    except OSError:
        return ()
    return tuple(stem for stem in stems if THEME_NAME.fullmatch(stem) and stem not in RESERVED_THEMES)


class ThemeCatalog:
    """Every palette that can be asked for by name, and where each comes from.

    There are three places, in this order: the two the terminal's own light or dark maps to (``dark`` and ``light``,
    which nothing can replace), the *sources* (the built-in plugin's files, then any other plugin's, in the order
    they loaded), and the reader's own ``<name>.toml`` files. A reader's file shadows a source of the same name,
    which is how a palette that ships is adjusted: copy it, change what is wrong with it, keep the name. A source
    whose name is taken is ignored, the first one winning.

    Only names are listed up front. A palette is built when it is asked for, so a catalog of sixty costs a start
    nothing.

    Args:
        sources: What plugins and the program offer.
        directory: The reader's palette directory; one that is missing is the same as an empty one.
    """

    def __init__(self, sources: Sequence[ThemeSource] = (), directory: Path | None = None) -> None:
        chosen: dict[str, ThemeSource] = {}
        for source in sources:
            if source.name not in RESERVED_THEMES and source.name not in chosen and THEME_NAME.fullmatch(source.name):
                chosen[source.name] = source
        self._sources = chosen
        self.directory = directory

    def names(self) -> tuple[str, ...]:
        """Return the names in the order a menu lists them. Nothing is parsed."""
        own = [name for name in _user_names(self.directory) if name not in self._sources]
        return (*RESERVED_THEMES, *self._sources, *own)

    def load(self, name: str) -> Theme:
        """Return the palette called ``name``.

        Raises:
            ThemeFileError: There is no such palette, or it cannot be built or understood. The message names what is
                available, so a typo is answered by the list.
        """
        if name in RESERVED_THEMES:
            # Chosen by name, they paint their own page like every other palette: a light one over a dark terminal is
            # light, not dark text on the terminal's black. Only the *automatic* pick leaves the page alone.
            return replace(theme_named(name), background=PAGES[name])
        path = _user_file(name, self.directory)
        if path is not None:
            loaded = load_theme(path)
        elif name in self._sources:
            try:
                loaded = self._sources[name].load()
            except ThemeFileError:
                raise
            except Exception as error:  # noqa: BLE001 - a plugin's palette is its author's code
                raise ThemeFileError(f"Theme {name!r} could not be built: {error}") from error
        else:
            raise ThemeFileError(f"Unknown theme: {name!r}. Available: {', '.join(self.names())}")
        return replace(loaded, name=name, code=replace(loaded.code, name=name))

    def notes(self) -> dict[str, str]:
        """Return the one-line note each palette carries, by name; a palette with none is left out.

        Read from the files and the plugins, so this is for a menu that is being opened and not for the start.
        Whatever cannot be read has no note, and is not an error here: it is the error of the person who picks it.
        """
        notes: dict[str, str] = {}
        for name in self.names():
            if name in RESERVED_THEMES:
                continue
            path = _user_file(name, self.directory)
            try:
                if path is not None:
                    data = tomllib.loads(path.read_text(encoding="utf-8")).get("description")
                else:
                    described = self._sources[name].description
                    data = described() if callable(described) else described
            except Exception:  # noqa: BLE001 - see above
                continue
            if isinstance(data, str) and data.strip():
                notes[name] = data.strip()
        return notes


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
