"""Terminal capability detection used to pick conservative rendering options."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from .render.color import ColorDepth

_TRUECOLOR_COLORTERM = {"truecolor", "24bit"}
_MOTION_VARIABLES = ("ZETTCODE_REDUCED_MOTION", "NO_MOTION", "REDUCED_MOTION")


@dataclass(frozen=True, slots=True)
class TerminalCapabilities:
    """What the attached terminal can be trusted to render.

    Attributes:
        color_depth: Safest depth the environment advertises.
        unicode: The locale looks like it can encode UTF-8. Advisory for now: no
            widget switches to an ASCII glyph set when it is False.
        mouse: The terminal accepts mouse reporting. Advisory, like ``unicode``.
        bracketed_paste: The terminal wraps pastes in ``ESC[200~`` guards.
            Advisory as well; the decoder accepts them either way.
        width: Initial width guess in cells, replaced on the first resize.
        height: Initial height guess in cells.
    """

    color_depth: ColorDepth = ColorDepth.ANSI16
    unicode: bool = True
    mouse: bool = True
    bracketed_paste: bool = True
    width: int = 80
    height: int = 24

    @property
    def truecolor(self) -> bool:
        """Return whether the terminal can be trusted with 24-bit colour."""
        return self.color_depth is ColorDepth.TRUECOLOR


def detect_capabilities(environ: Mapping[str, str] | None = None) -> TerminalCapabilities:
    """Derive capabilities from environment variables.

    Everything here is a heuristic, so each default errs toward the option that
    still looks correct on a weaker terminal.

    Args:
        environ: Environment to read; defaults to ``os.environ`` and is
            injectable so tests can describe a terminal without owning one.
    """
    env = os.environ if environ is None else environ
    return TerminalCapabilities(
        color_depth=detect_color_depth(env),
        unicode=detect_unicode(env),
    )


def detect_color_depth(environ: Mapping[str, str] | None = None) -> ColorDepth:
    """Return the safest color depth the environment advertises.

    Args:
        environ: Environment to read; defaults to ``os.environ``.
    """
    env = os.environ if environ is None else environ
    term = env.get("TERM", "")
    if env.get("NO_COLOR") or term == "dumb":
        return ColorDepth.MONO
    colorterm = env.get("COLORTERM", "").lower()
    if colorterm in _TRUECOLOR_COLORTERM or "truecolor" in term or "direct" in term:
        return ColorDepth.TRUECOLOR
    if "256" in term or colorterm:
        return ColorDepth.ANSI256
    return ColorDepth.ANSI16


def detect_unicode(environ: Mapping[str, str] | None = None) -> bool:
    """Return whether the environment looks like it can encode UTF-8.

    Args:
        environ: Environment to read; defaults to ``os.environ``. An unset
            locale is treated as UTF-8 capable, because that is the common case
            on modern systems.
    """
    env = os.environ if environ is None else environ
    locale = env.get("LC_ALL") or env.get("LC_CTYPE") or env.get("LANG", "")
    if locale:
        return "utf" in locale.lower()
    return True


def detect_reduced_motion(environ: Mapping[str, str] | None = None) -> bool:
    """Return whether decorative animation should be suppressed.

    Args:
        environ: Environment to read; defaults to ``os.environ``. Any of
            ``_MOTION_VARIABLES`` being set to a non-empty value wins.
    """
    env = os.environ if environ is None else environ
    return any(env.get(name) for name in _MOTION_VARIABLES)
