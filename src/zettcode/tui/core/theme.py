"""Semantic color tokens that widgets render against."""

from __future__ import annotations

from dataclasses import dataclass

from ..render.code import CodeTheme


@dataclass(frozen=True, slots=True)
class Theme:
    """One named palette expressed as semantic roles, never raw hex.

    Widgets read roles such as ``accent`` or ``muted`` so a new palette is a
    data change rather than a search-and-replace through every component.

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
    background: str = "#0f1412"
    surface: str = "#161c18"
    surface_alt: str = "#222725"
    text: str = "#e6e9e7"
    muted: str = "#747d77"
    subtle: str = "#a3ada6"
    accent: str = "#79b88b"
    accent_bright: str = "#9bddad"
    warning: str = "#d8b46a"
    error: str = "#dc8178"
    border: str = "#343a36"
    focus: str = "#60876b"
    selection: str = "#2f4a38"
    code: CodeTheme = CodeTheme()


DARK = Theme()

LIGHT = Theme(
    name="light",
    background="#f7f8f7",
    surface="#ffffff",
    surface_alt="#eceeec",
    text="#1b211d",
    muted="#6d766f",
    subtle="#4c554e",
    accent="#2f7a48",
    accent_bright="#256b3b",
    warning="#8a6314",
    error="#b23b30",
    border="#c9cfca",
    focus="#2f7a48",
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
