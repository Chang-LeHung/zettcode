"""Terminal color depth and the SGR encoding derived from it."""

from __future__ import annotations

from enum import IntEnum
from functools import lru_cache

from .style import Style

_CUBE_STEPS = (0, 95, 135, 175, 215, 255)

_ANSI16_RGB: tuple[tuple[int, int, int], ...] = (
    (0, 0, 0),
    (205, 0, 0),
    (0, 205, 0),
    (205, 205, 0),
    (0, 0, 238),
    (205, 0, 205),
    (0, 205, 205),
    (229, 229, 229),
    (127, 127, 127),
    (255, 0, 0),
    (0, 255, 0),
    (255, 255, 0),
    (92, 92, 255),
    (255, 0, 255),
    (0, 255, 255),
    (255, 255, 255),
)

_ANSI256_RGB: tuple[tuple[int, int, int], ...] = (
    *_ANSI16_RGB,
    *((red, green, blue) for red in _CUBE_STEPS for green in _CUBE_STEPS for blue in _CUBE_STEPS),
    *((level, level, level) for level in range(8, 8 + 24 * 10, 10)),
)


class ColorDepth(IntEnum):
    """How many distinct colors the terminal can paint."""

    MONO = 1
    ANSI16 = 16
    ANSI256 = 256
    TRUECOLOR = 1 << 24


@lru_cache(maxsize=1024)
def parse_hex(value: str) -> tuple[int, int, int] | None:
    """Parse ``#rrggbb`` into channels, returning None for anything else."""
    digits = value.removeprefix("#")
    if len(digits) != 6:
        return None
    try:
        return int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16)
    except ValueError:
        return None


@lru_cache(maxsize=4096)
def rgb_to_ansi256(red: int, green: int, blue: int) -> int:
    """Return the closest index in the standard 256-color palette.

    Args:
        red: Channel value in ``0..255``.
        green: Channel value in ``0..255``.
        blue: Channel value in ``0..255``.
    """
    return _nearest(_ANSI256_RGB, red, green, blue)


@lru_cache(maxsize=4096)
def rgb_to_ansi16(red: int, green: int, blue: int) -> int:
    """Return the closest index in the standard 16-color palette.

    Args:
        red: Channel value in ``0..255``.
        green: Channel value in ``0..255``.
        blue: Channel value in ``0..255``.
    """
    return _nearest(_ANSI16_RGB, red, green, blue)


def encode_style(style: Style, depth: ColorDepth = ColorDepth.TRUECOLOR) -> str:
    """Encode one style as an SGR sequence for the given color depth.

    Args:
        style: Style to encode; colours are approximated, attributes are exact.
        depth: How precisely the terminal can paint a colour. ``MONO`` drops
            colours entirely but still emits bold, dim, italic, and reverse.
    """
    # SGR 0 first, so the run starts from a known state and an attribute that
    # was set earlier can never survive into this one.
    codes = ["0"]
    if style.bold:
        codes.append("1")  # SGR 1: bold
    if style.dim:
        codes.append("2")  # SGR 2: faint
    if style.italic:
        codes.append("3")  # SGR 3: italic
    if style.reverse:
        codes.append("7")  # SGR 7: reverse video, used for text selection
    if depth is not ColorDepth.MONO:
        if style.foreground:
            color = _color(style.foreground, depth, foreground=True)
            if color:
                codes.append(color)
        if style.background:
            color = _color(style.background, depth, foreground=False)
            if color:
                codes.append(color)
    return f"\x1b[{';'.join(codes)}m"  # CSI ... m: Select Graphic Rendition


def _color(value: str, depth: ColorDepth, *, foreground: bool) -> str:
    """Encode one hex colour as the SGR parameters the depth supports."""
    rgb = parse_hex(value)
    if rgb is None:
        return ""
    # SGR 38 selects a foreground colour, 48 the background; the parameter that
    # follows picks how the colour is spelled.
    base = 38 if foreground else 48
    if depth is ColorDepth.TRUECOLOR:
        # ``;2;r;g;b`` is 24-bit colour, one byte per channel.
        return f"{base};2;{rgb[0]};{rgb[1]};{rgb[2]}"
    if depth is ColorDepth.ANSI256:
        # ``;5;n`` indexes the 256-colour cube.
        return f"{base};5;{rgb_to_ansi256(*rgb)}"
    index = rgb_to_ansi16(*rgb)
    if index < 8:
        # SGR 30-37 for foreground and 40-47 for background name the base eight.
        return str((30 if foreground else 40) + index)
    # SGR 90-97 and 100-107 are the bright half of the same palette.
    return str((90 if foreground else 100) + index - 8)


def _nearest(palette: tuple[tuple[int, int, int], ...], red: int, green: int, blue: int) -> int:
    """Return the index of the palette entry closest to one RGB triple."""
    best_index = 0
    best_distance: int | None = None
    for index, (candidate_red, candidate_green, candidate_blue) in enumerate(palette):
        distance = (candidate_red - red) ** 2 + (candidate_green - green) ** 2 + (candidate_blue - blue) ** 2
        if best_distance is None or distance < best_distance:
            best_index, best_distance = index, distance
    return best_index
