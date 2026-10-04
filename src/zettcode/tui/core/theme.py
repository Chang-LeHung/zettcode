"""Semantic color tokens that widgets render against."""

from __future__ import annotations

from dataclasses import dataclass

from ..render.code import CodeTheme


@dataclass(frozen=True, slots=True)
class Theme:
    """One named palette expressed as semantic roles, never raw hex.

    Widgets read roles such as ``accent`` or ``muted`` so a new palette is a
    data change rather than a search-and-replace through every component.

    The built-in dark palette follows Everforest's green-leaning accents
    (``#A7C080`` green, ``#83C092`` aqua, ``#DBBC7F`` yellow, ``#E67E80`` red)
    over the neutral greys, so a transcript can tell reasoning from tool output
    by hue instead of drawing every row in one green.

    Attributes:
        name: Palette key used by ``/theme`` and by ``base =`` in a theme file.
        background: Page fill behind everything.
        surface: Raised panel fill.
        surface_alt: Fill shared by the composer and submitted user messages.
        text: Body text.
        muted: Lowest-emphasis text (hints, timestamps, disabled rows).
        subtle: Secondary body text that must stay readable, such as a reasoning
            body or an unchanged diff line.
        accent: Primary highlight: running rows, list markers, the selection
            bullet in a tool row.
        accent_bright: Emphasised accent: the composer prompt, link targets,
            hunk headers.
        warning: Warning state, currently the warning toast.
        error: Failure state: failed tool rows and the error toast.
        border: Frame glyphs and separators.
        focus: Focus ring colour; reserved, no built-in widget draws a ring yet.
        selection: Background of a selected or emphasised cell, used by list
            rows and diff segments; text selection uses reverse video instead.
        code: Per-token palette for fenced code blocks.
    """

    name: str = "dark"
    background: str = "#232a2e"
    surface: str = "#2d353b"
    surface_alt: str = "#343f44"
    text: str = "#f2f5f3"
    muted: str = "#7a8478"
    subtle: str = "#9da9a0"
    accent: str = "#a7c080"
    accent_bright: str = "#83c092"
    warning: str = "#dbbc7f"
    error: str = "#e67e80"
    border: str = "#3d484d"
    focus: str = "#83c092"
    selection: str = "#4a5f52"
    code: CodeTheme = CodeTheme()


DARK = Theme()

LIGHT = Theme(
    name="light",
    background="#f7f8f7",
    surface="#ffffff",
    surface_alt="#eceeec",
    text="#1b211d",
    muted="#68736c",
    subtle="#4c554e",
    accent="#5f7a10",
    accent_bright="#237a5c",
    warning="#8a6314",
    error="#b23b30",
    border="#bdc3af",
    focus="#237a5c",
    selection="#cfe4d6",
    code=CodeTheme(
        name="light",
        inline="#256b3b",
        text="#1b211d",
        keyword="#a3234a",
        string="#2f7a48",
        comment="#6d766f",
        number="#8a6314",
        function="#1f5f8b",
        builtin="#5b3fa8",
        operator="#4c554e",
        punctuator="#4c554e",
    ),
)


def theme_named(name: str) -> Theme:
    """Return the built-in theme registered under a name."""
    if name == DARK.name:
        return DARK
    if name == LIGHT.name:
        return LIGHT
    raise ValueError(f"Unknown theme: {name!r}")


def theme_names() -> tuple[str, ...]:
    """Return the built-in palette keys, in the order a picker should list them."""
    return (DARK.name, LIGHT.name)
