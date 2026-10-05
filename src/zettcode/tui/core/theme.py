"""Semantic color tokens that widgets render against."""

from __future__ import annotations

from dataclasses import dataclass

from ..render.code import CodeTheme
from ..render.color import parse_hex


@dataclass(frozen=True, slots=True)
class ToolTheme:
    """The colour a tool row is painted with, by what the tool did.

    The built-in palettes paint every tool with the code palette's builtin
    violet — the colour a reader already knows from ``print`` and ``__main__``
    in a snippet — which is what a transcript wants until its reader knows the
    tools by heart. The roles are separate so a theme file can pull them apart —
    one hue for reading, another for running — without touching any code. A tool
    the palette has never heard of, and any role left unset, falls back to
    :attr:`Theme.accent`.

    Attributes:
        read: Reading one file, the least surprising action.
        search: Finding paths or matches across the workspace.
        image: Looking at a picture rather than text.
        write: Creating a file or editing one in place.
        delete: Removing a path; deliberately the same hue as a failure.
        shell: Running a command in the workspace.
        plan: Recording the task list.
        subagent: Delegating work to an isolated child agent, which is its own
            family rather than a file operation.
    """

    read: str = "#b8a6e0"
    search: str = "#b8a6e0"
    image: str = "#b8a6e0"
    write: str = "#b8a6e0"
    delete: str = "#b8a6e0"
    shell: str = "#b8a6e0"
    plan: str = "#b8a6e0"
    subagent: str = "#8fcfc6"


@dataclass(frozen=True, slots=True)
class Theme:
    """One named palette expressed as semantic roles, never raw hex.

    Widgets read roles such as ``accent`` or ``muted`` so a new palette is a
    data change rather than a search-and-replace through every component.

    The built-in palettes leave the page to the terminal and follow
    Everforest's green-leaning accents
    (``#A7C080`` green, ``#83C092`` aqua, ``#DBBC7F`` yellow, ``#E67E80`` red)
    over the neutral greys, so a transcript can tell reasoning from tool output
    by hue instead of drawing every row in one green.

    Attributes:
        name: Palette key used by ``/theme`` and by ``base =`` in a theme file.
        background: Page fill behind everything; ``None`` — what both built-in
            palettes use — leaves the terminal's own background in place, so the
            shell blends into the profile it was started in.
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
        tools: Per-tool palette for agent rows; see :class:`ToolTheme`.
        code: Per-token palette for fenced code blocks.
    """

    name: str = "dark"
    background: str | None = None
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
    tools: ToolTheme = ToolTheme()
    code: CodeTheme = CodeTheme()


DARK = Theme()

LIGHT = Theme(
    name="light",
    background=None,
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
    tools=ToolTheme(
        read="#5b3fa8",
        search="#5b3fa8",
        image="#5b3fa8",
        write="#5b3fa8",
        delete="#5b3fa8",
        shell="#5b3fa8",
        plan="#5b3fa8",
        subagent="#1e7f76",
    ),
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


def scheme_named(background: str | None) -> str | None:
    """Return ``"light"`` or ``"dark"`` for a background colour, or None without one.

    Used to follow the terminal: the luminance of what it says its background is
    picks the palette, so the shell matches the profile it was started in.

    Args:
        background: ``#rrggbb`` colour, or None when nothing was reported.
    """
    channels = parse_hex(background) if background else None
    if channels is None:
        return None
    red, green, blue = (channel / 255 for channel in channels)
    luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
    return "light" if luminance > 0.5 else "dark"


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
