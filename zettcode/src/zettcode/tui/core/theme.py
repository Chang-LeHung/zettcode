"""Semantic color tokens that widgets render against."""

from __future__ import annotations

from dataclasses import dataclass

from ..render.code import CodeTheme
from ..render.color import blend, parse_hex

#: How much of a diff line's colour is mixed into the page to make the fill behind that line.
DIFF_FILL_SHARE = 0.16


@dataclass(frozen=True, slots=True)
class ToolTheme:
    """The colour a tool row is painted with, by what the tool did.

    The built-in palettes keep to a few hues, the way editors keep their tool and
    status colours to a few: a soft lavender for what the agent goes looking with
    (a glob, a grep, a picture, a command, the plan), a yellow for reading one
    file, orange for what it writes, red for what it deletes, teal for a delegated
    child agent, and mauve for talking to another session. More hues than that read as noise in a
    transcript that is mostly tool rows, so reading is the one addition: those rows are the most
    of any, and a yellow no other role claims says "this is a file I read" where the lavender says
    "this is the agent doing something". Writing is orange and not green because green is the
    colour of an added line: the heading of an edit sits on the line above its diff, and the same
    green on both made the heading read as one more added line (and a yellow one, close to the
    green in hue and weight, still read as its neighbour). The roles are separate so a theme
    file can pull them apart without touching any code. A tool the palette has never heard of, and
    any role left unset, falls back to :attr:`Theme.accent`.

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
        message: Talking to another session: ``send_message`` and ``list_sessions``, and the
            header of a message another session's agent sent. One hue for both directions, so a
            conversation between sessions reads as one thing.
        web_search: A search the endpoint ran on the model's behalf (``web_search``). Its own
            role rather than ``search``: it leaves the workspace for the open web, and a theme
            may say so. Spelled ``web-search`` in a theme file's ``[tools]`` table.
        ask_user: A question the model put to the reader (``ask_user``). Its own role rather than
            ``plan``: it is the one row that waits for a person, and a theme may colour it apart.
            Spelled ``ask-user`` in a theme file's ``[tools]`` table.
    """

    read: str = "#f9e2af"
    search: str = "#b4befe"
    image: str = "#b4befe"
    write: str = "#ef9a62"
    delete: str = "#e67e80"
    shell: str = "#b4befe"
    plan: str = "#b4befe"
    subagent: str = "#94e2d5"
    message: str = "#cba6f7"
    web_search: str = "#b4befe"
    ask_user: str = "#b4befe"


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
        surface_side: Fill of a side question, which is answered on screen and
            deliberately kept out of the conversation. It stays as quiet as any
            other background — the muted body colour has to remain readable on
            it — but it leans a different way from the green-toned neutrals, a
            soft slate, so an aside reads as a note beside the conversation
            rather than as one of its turns.
        surface_peer: Fill of a message that crossed between two sessions, in either direction. It
            is drawn like the reader's own message (the arrow, the same text column), so only its
            background says it is not the reader's. It is as light as ``surface_alt`` and only leans another way —
            Catppuccin Mocha's lavender-grey ``surface0`` in the dark palette, a pale sage in the light one —
            so it reads as a neighbour of the reader's message rather than as a hole or a banner next to it.
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
        diff_added: A line a change adds, and the ``+N`` beside the file. ``None`` — what both built-in
            palettes use — means :attr:`accent`, so a theme that changes the accent changes the diff
            with it; set it to colour additions on their own. Read it through :attr:`addition`.
        diff_removed: A line a change removes, and the ``-N`` beside the file. ``None`` means
            :attr:`error`. Read it through :attr:`deletion`.
        diff_added_fill: The band behind an added line of an edit. ``None`` mixes :attr:`addition` into the page
            (:attr:`background`, or :attr:`surface` when the page is the terminal's), so the band follows the
            palette. Read it through :attr:`addition_fill`.
        diff_removed_fill: The same for a removed line; read it through :attr:`deletion_fill`.
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
    surface_side: str = "#393a44"
    surface_peer: str = "#313244"
    text: str = "#f2f5f3"
    muted: str = "#7a8478"
    subtle: str = "#9da9a0"
    accent: str = "#a7c080"
    accent_bright: str = "#83c092"
    warning: str = "#dbbc7f"
    error: str = "#e67e80"
    diff_added: str | None = None
    diff_removed: str | None = None
    diff_added_fill: str | None = None
    diff_removed_fill: str | None = None
    border: str = "#3d484d"
    focus: str = "#83c092"
    selection: str = "#4a5f52"
    tools: ToolTheme = ToolTheme()
    code: CodeTheme = CodeTheme()

    @property
    def addition_fill(self) -> str:
        """Return the fill behind an added line: ``diff_added_fill`` if set, else the addition colour mixed into the page."""
        return self.diff_added_fill or blend(self.background or self.surface, self.addition, DIFF_FILL_SHARE)

    @property
    def deletion_fill(self) -> str:
        """Return the fill behind a removed line: ``diff_removed_fill`` if set, else the deletion colour mixed in."""
        return self.diff_removed_fill or blend(self.background or self.surface, self.deletion, DIFF_FILL_SHARE)

    @property
    def addition(self) -> str:
        """Return the colour of an added line: ``diff_added`` if set, else the accent."""
        return self.diff_added or self.accent

    @property
    def deletion(self) -> str:
        """Return the colour of a removed line: ``diff_removed`` if set, else the error colour."""
        return self.diff_removed or self.error


DARK = Theme()

LIGHT = Theme(
    name="light",
    background=None,
    surface="#ffffff",
    surface_alt="#eceeec",
    surface_side="#e5e6ee",
    surface_peer="#e1ebe4",
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
        read="#7a5c00",
        search="#5b3fa8",
        image="#5b3fa8",
        write="#b85a14",
        delete="#b23b30",
        shell="#5b3fa8",
        plan="#5b3fa8",
        subagent="#1e7f76",
        message="#8a4a9e",
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
