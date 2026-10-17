"""Candidate palettes for the interface, written as a small vocabulary each and turned into full themes.

Every palette names the colours it is known for (its background, a raised surface, text, five accents) and the
rest of the roles ``Theme`` asks for are derived from those the same way for all of them, so the palettes differ
by their colours and not by how carefully each one was wired. Where a palette's own greys would be too faint to
read a hint in (comment greys usually are), :func:`tuned` nudges the colour toward the text just far enough to
pass, and records that it did, so the gallery can say which colours are the palette's own and which were moved.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from zettcode.tui import DARK, LIGHT, Theme
from zettcode.tui.core.theme import ToolTheme
from zettcode.tui.render import blend
from zettcode.tui.render.code import CodeTheme
from zettcode.tui.render.color import parse_hex

#: Least contrast a coloured word may have on the page. Below the 4.5 of body text on purpose: a pastel palette
#: is pastel because its accents are soft, and the lines they colour are short; the greys that carry sentences
#: are held higher.
ACCENT_MIN = 4.0


def luminance(colour: str) -> float:
    """Return the WCAG relative luminance of a ``#rrggbb`` colour."""
    channels = parse_hex(colour)
    assert channels is not None, colour
    linear = [((c / 255) / 12.92) if c / 255 <= 0.03928 else (((c / 255) + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(first: str, second: str) -> float:
    """Return the WCAG contrast ratio between two colours, 1 to 21."""
    a, b = luminance(first), luminance(second)
    high, low = max(a, b), min(a, b)
    return (high + 0.05) / (low + 0.05)


@dataclass(frozen=True)
class Palette:
    """One candidate: a name, a mood in a sentence, and the theme it builds."""

    key: str
    label: str
    mood: str
    dark: bool
    theme: Theme
    #: Roles whose colour was moved to reach a readable contrast, as ``{role: (original, tuned)}``.
    tuned: dict[str, tuple[str, str]] = field(default_factory=dict)


def tuned(colour: str, against: tuple[str, ...], minimum: float, toward: str) -> str:
    """Return ``colour`` moved toward ``toward`` until it reaches ``minimum`` contrast on every background."""
    result = colour
    for step in range(0, 41):
        result = blend(colour, toward, step / 40)
        if all(contrast(result, background) >= minimum for background in against):
            return result
    return result


def build(
    key: str,
    label: str,
    mood: str,
    *,
    dark: bool,
    bg: str,
    surface: str,
    alt: str,
    text: str,
    muted: str,
    subtle: str,
    border: str,
    selection: str,
    accent: str,
    bright: str,
    red: str,
    orange: str,
    yellow: str,
    green: str,
    teal: str,
    blue: str,
    purple: str,
    pink: str,
    keyword: str | None = None,
    cool: str | None = None,
    write: str | None = None,
) -> Palette:
    """Turn a palette's vocabulary into a theme, tuning the colours that would be unreadable."""
    toward = "#ffffff" if dark else "#000000"
    side = blend(alt, blue, 0.10)
    peer = blend(alt, purple, 0.13)
    backgrounds = (bg, alt)
    moved: dict[str, tuple[str, str]] = {}

    def fit(role: str, colour: str, minimum: float, against: tuple[str, ...] = (bg,)) -> str:
        fixed = tuned(colour, against, minimum, toward)
        if fixed != colour:
            moved[role] = (colour, fixed)
        return fixed

    # Greys that carry words are held to the raised fill as well as the page; coloured accents only to the page.
    text = fit("text", text, 7.0, backgrounds)
    muted = fit("muted", muted, 4.0, backgrounds)
    subtle = fit("subtle", subtle, 5.5, backgrounds)
    accent = fit("accent", accent, ACCENT_MIN)
    bright = fit("accent_bright", bright, ACCENT_MIN)
    warning = fit("warning", yellow, ACCENT_MIN)
    error = fit("error", red, ACCENT_MIN)
    green = fit("diff_added", green, ACCENT_MIN)
    cool = fit("tools.read", cool or blue, ACCENT_MIN)
    # Writing is the orange, not the yellow: the heading of an edit sits right above a diff whose additions are green,
    # and a yellow heading is close to that green in hue and weight.
    writes = fit("tools.write", write or orange, ACCENT_MIN)
    delete = fit("tools.delete", red, ACCENT_MIN)
    teal = fit("tools.subagent", teal, ACCENT_MIN)
    message = fit("tools.message", pink if pink != accent else purple, ACCENT_MIN)
    code = CodeTheme(
        name=key,
        inline=fit("code.inline", green, ACCENT_MIN),
        text=text,
        keyword=fit("code.keyword", keyword or pink, ACCENT_MIN),
        string=fit("code.string", green, ACCENT_MIN),
        comment=fit("code.comment", muted, 4.0),
        number=fit("code.number", orange, ACCENT_MIN),
        function=fit("code.function", blue, ACCENT_MIN),
        builtin=fit("code.builtin", purple, ACCENT_MIN),
        operator=subtle,
        punctuator=subtle,
    )
    theme = Theme(
        name=key,
        background=bg,
        surface=surface,
        surface_alt=alt,
        surface_side=side,
        surface_peer=peer,
        text=text,
        muted=muted,
        subtle=subtle,
        accent=accent,
        accent_bright=bright,
        warning=warning,
        error=error,
        diff_added=green,
        diff_removed=error,
        border=border,
        focus=bright,
        selection=selection,
        tools=ToolTheme(
            read=cool,
            search=cool,
            image=cool,
            write=writes,
            delete=delete,
            shell=cool,
            plan=cool,
            subagent=teal,
            message=message,
        ),
        code=code,
    )
    return Palette(key, label, mood, dark, theme, moved)


def current(theme: Theme, label: str, mood: str, *, dark: bool, bg: str) -> Palette:
    """The palette shipped today, unchanged, so every candidate can be judged against it."""
    return Palette(theme.name, label, mood, dark, replace(theme, background=bg))


#: One line per palette, as the ``/theme`` menu shows it beside the name. These ship inside the theme files.
NOTES = {
    "catppuccin-mocha": "soft purple-grey, pastel accents",
    "tokyo-night": "deep indigo, cool neon blues",
    "nord": "arctic blue-grey, very low saturation",
    "gruvbox-dark": "warm brown-yellow, retro paper",
    "rose-pine": "dark violet with rose gold",
    "kanagawa": "ink blue and faded gold",
    "dracula": "vivid purple, pink and green",
    "one-dark": "Atom's neutral blue-grey classic",
    "solarized-dark": "deep teal, low contrast",
    "github-dimmed": "GitHub's dimmed dark, restrained",
    "ayu-mirage": "blue-grey with warm gold",
    "catppuccin-latte": "creamy lavender-grey, saturated accents",
    "rose-pine-dawn": "warm paper with violet and rose",
    "gruvbox-light": "cream paper, brown text",
    "solarized-light": "beige with teal-blue accents",
    "github-light": "plain white, standard blue/green/red",
}


def palettes() -> tuple[Palette, ...]:
    """Return every candidate, the shipped ones first, then dark palettes, then light ones."""
    return (
        current(
            DARK,
            "当前 · 暗色 (Everforest 绿)",
            "现在的默认暗色：偏绿的森林灰，眼睛最松，识别度来自绿色。",
            dark=True,
            bg="#232a2e",
        ),
        build(
            "catppuccin-mocha",
            "Catppuccin Mocha",
            "柔和的紫灰底，粉彩色点缀；对比温和，长时间看不累，二次元味最浓。",
            dark=True,
            bg="#1e1e2e",
            surface="#262637",
            alt="#313244",
            text="#cdd6f4",
            muted="#7f849c",
            subtle="#a6adc8",
            border="#45475a",
            selection="#45475a",
            accent="#cba6f7",
            bright="#b4befe",
            red="#f38ba8",
            orange="#fab387",
            yellow="#f9e2af",
            green="#a6e3a1",
            teal="#94e2d5",
            blue="#89b4fa",
            purple="#cba6f7",
            pink="#f5c2e7",
            keyword="#cba6f7",
            cool="#b4befe",
        ),
        build(
            "tokyo-night",
            "Tokyo Night",
            "深靛蓝底，冷色霓虹感；干净、偏“科技”，蓝紫系主调。",
            dark=True,
            bg="#1a1b26",
            surface="#1f2335",
            alt="#292e42",
            text="#c0caf5",
            muted="#6b7399",
            subtle="#a9b1d6",
            border="#3b4261",
            selection="#2f3b66",
            accent="#7aa2f7",
            bright="#7dcfff",
            red="#f7768e",
            orange="#ff9e64",
            yellow="#e0af68",
            green="#9ece6a",
            teal="#73daca",
            blue="#7aa2f7",
            purple="#bb9af7",
            pink="#bb9af7",
            keyword="#bb9af7",
        ),
        build(
            "nord",
            "Nord",
            "北欧冰蓝灰，饱和度很低；最克制、最“安静”，不抢正文。",
            dark=True,
            bg="#2e3440",
            surface="#343b49",
            alt="#3b4252",
            text="#eceff4",
            muted="#7b88a1",
            subtle="#d8dee9",
            border="#4c566a",
            selection="#434c5e",
            accent="#88c0d0",
            bright="#8fbcbb",
            red="#bf616a",
            orange="#d08770",
            yellow="#ebcb8b",
            green="#a3be8c",
            teal="#8fbcbb",
            blue="#81a1c1",
            purple="#b48ead",
            pink="#b48ead",
            keyword="#81a1c1",
        ),
        build(
            "gruvbox-dark",
            "Gruvbox Dark",
            "暖棕黄底，复古纸感；对比度高、颜色偏土，和现在的绿灰形成最大反差。",
            dark=True,
            bg="#282828",
            surface="#32302f",
            alt="#3c3836",
            text="#ebdbb2",
            muted="#928374",
            subtle="#bdae93",
            border="#504945",
            selection="#504945",
            accent="#fe8019",
            bright="#fabd2f",
            red="#fb4934",
            orange="#fe8019",
            yellow="#d79921",
            green="#b8bb26",
            teal="#8ec07c",
            blue="#83a598",
            purple="#d3869b",
            pink="#d3869b",
            keyword="#fb4934",
        ),
        build(
            "rose-pine",
            "Rosé Pine",
            "深紫黑底配玫瑰金与鸢尾紫；浪漫、有点“高级感”，没有真正的绿色（成功用青蓝）。",
            dark=True,
            bg="#191724",
            surface="#1f1d2e",
            alt="#26233a",
            text="#e0def4",
            muted="#6e6a86",
            subtle="#908caa",
            border="#403d52",
            selection="#403d52",
            accent="#c4a7e7",
            bright="#ebbcba",
            red="#eb6f92",
            orange="#ebbcba",
            yellow="#f6c177",
            green="#9ccfd8",
            teal="#9ccfd8",
            blue="#31748f",
            purple="#c4a7e7",
            pink="#eb6f92",
            keyword="#31748f",
            cool="#9ccfd8",
        ),
        build(
            "kanagawa",
            "Kanagawa Wave",
            "浮世绘的墨蓝与枯黄；低饱和、有质感，红金点缀很雅。",
            dark=True,
            bg="#1f1f28",
            surface="#252535",
            alt="#2a2a37",
            text="#dcd7ba",
            muted="#727169",
            subtle="#c8c093",
            border="#363646",
            selection="#2d4f67",
            accent="#7e9cd8",
            bright="#7fb4ca",
            red="#e46876",
            orange="#ffa066",
            yellow="#e6c384",
            green="#98bb6c",
            teal="#7aa89f",
            blue="#7e9cd8",
            purple="#957fb8",
            pink="#d27e99",
            keyword="#957fb8",
        ),
        build(
            "dracula",
            "Dracula",
            "高饱和的紫粉绿霓虹；最鲜艳、最有辨识度，但长时间看偏刺眼。",
            dark=True,
            bg="#282a36",
            surface="#2f3140",
            alt="#343746",
            text="#f8f8f2",
            muted="#6272a4",
            subtle="#bdc0d6",
            border="#44475a",
            selection="#44475a",
            accent="#bd93f9",
            bright="#ff79c6",
            red="#ff5555",
            orange="#ffb86c",
            yellow="#f1fa8c",
            green="#50fa7b",
            teal="#8be9fd",
            blue="#8be9fd",
            purple="#bd93f9",
            pink="#ff79c6",
            keyword="#ff79c6",
        ),
        build(
            "one-dark",
            "One Dark",
            "Atom 经典：中性蓝灰底，红绿蓝黄都很“标准”；最不会出错的稳妥选择。",
            dark=True,
            bg="#282c34",
            surface="#2c313a",
            alt="#333842",
            text="#abb2bf",
            muted="#5c6370",
            subtle="#9da5b4",
            border="#3e4451",
            selection="#3e4451",
            accent="#61afef",
            bright="#56b6c2",
            red="#e06c75",
            orange="#d19a66",
            yellow="#e5c07b",
            green="#98c379",
            teal="#56b6c2",
            blue="#61afef",
            purple="#c678dd",
            pink="#c678dd",
            keyword="#c678dd",
        ),
        build(
            "solarized-dark",
            "Solarized Dark",
            "深青蓝底，为低对比设计的老牌配色；护眼但字偏灰，需要适应。",
            dark=True,
            bg="#002b36",
            surface="#073642",
            alt="#0b3d4b",
            text="#93a1a1",
            muted="#657b83",
            subtle="#839496",
            border="#14505f",
            selection="#0f4c5c",
            accent="#268bd2",
            bright="#2aa198",
            red="#dc322f",
            orange="#cb4b16",
            yellow="#b58900",
            green="#859900",
            teal="#2aa198",
            blue="#268bd2",
            purple="#6c71c4",
            pink="#d33682",
            keyword="#859900",
        ),
        build(
            "github-dimmed",
            "GitHub Dark Dimmed",
            "GitHub 的“调暗”主题：灰蓝底、克制的高光，看起来像一个成熟的产品界面。",
            dark=True,
            bg="#22272e",
            surface="#2d333b",
            alt="#373e47",
            text="#adbac7",
            muted="#768390",
            subtle="#909dab",
            border="#444c56",
            selection="#2f4766",
            accent="#539bf5",
            bright="#6cb6ff",
            red="#e5534b",
            orange="#cc6b2c",
            yellow="#c69026",
            green="#57ab5a",
            teal="#39c5cf",
            blue="#539bf5",
            purple="#986ee2",
            pink="#e275ad",
            keyword="#f47067",
        ),
        build(
            "ayu-mirage",
            "Ayu Mirage",
            "暖金色强调配蓝灰底；比 Gruvbox 更现代、更轻，金色很显眼。",
            dark=True,
            bg="#1f2430",
            surface="#242936",
            alt="#2d3446",
            text="#cccac2",
            muted="#707a8c",
            subtle="#9aa3b2",
            border="#33415e",
            selection="#34455a",
            accent="#ffcc66",
            bright="#ffd173",
            red="#f28779",
            orange="#ffad66",
            yellow="#ffcc66",
            green="#87d96c",
            teal="#5ccfe6",
            blue="#73d0ff",
            purple="#dfbfff",
            pink="#f29e74",
            keyword="#ffad66",
        ),
        current(
            LIGHT,
            "当前 · 亮色 (Everforest 绿)",
            "现在的默认亮色：白底、深绿，干净但有点平。",
            dark=False,
            bg="#f7f8f5",
        ),
        build(
            "catppuccin-latte",
            "Catppuccin Latte",
            "奶咖色的浅紫灰底，粉彩变成饱和的深色；亮色里最甜、最可爱。",
            dark=False,
            bg="#eff1f5",
            surface="#f7f8fb",
            alt="#e6e9ef",
            text="#4c4f69",
            muted="#7c7f93",
            subtle="#5c5f77",
            border="#ccd0da",
            selection="#ccd0da",
            accent="#8839ef",
            bright="#7287fd",
            red="#d20f39",
            orange="#fe640b",
            yellow="#df8e1d",
            green="#40a02b",
            teal="#179299",
            blue="#1e66f5",
            purple="#8839ef",
            pink="#ea76cb",
            keyword="#8839ef",
            cool="#7287fd",
        ),
        build(
            "rose-pine-dawn",
            "Rosé Pine Dawn",
            "暖米色底配紫与玫瑰；温柔、像纸，亮色里最有气质。",
            dark=False,
            bg="#faf4ed",
            surface="#fffaf3",
            alt="#f2e9e1",
            text="#575279",
            muted="#9893a5",
            subtle="#797593",
            border="#dfdad9",
            selection="#dfdad9",
            accent="#907aa9",
            bright="#d7827e",
            red="#b4637a",
            orange="#d7827e",
            yellow="#ea9d34",
            green="#56949f",
            teal="#56949f",
            blue="#286983",
            purple="#907aa9",
            pink="#b4637a",
            keyword="#286983",
            cool="#56949f",
            write="#ea9d34",
        ),
        build(
            "gruvbox-light",
            "Gruvbox Light",
            "奶黄纸张底，棕黑字；复古、对比足，和暗色版成对。",
            dark=False,
            bg="#fbf1c7",
            surface="#f9f5d7",
            alt="#ebdbb2",
            text="#3c3836",
            muted="#7c6f64",
            subtle="#504945",
            border="#d5c4a1",
            selection="#d5c4a1",
            accent="#af3a03",
            bright="#b57614",
            red="#9d0006",
            orange="#af3a03",
            yellow="#b57614",
            green="#79740e",
            teal="#427b58",
            blue="#076678",
            purple="#8f3f71",
            pink="#8f3f71",
            keyword="#9d0006",
        ),
        build(
            "solarized-light",
            "Solarized Light",
            "米色底，青蓝强调；经典护眼亮色，字色偏灰蓝。",
            dark=False,
            bg="#fdf6e3",
            surface="#fffbf0",
            alt="#eee8d5",
            text="#586e75",
            muted="#93a1a1",
            subtle="#657b83",
            border="#ddd6c1",
            selection="#e4ddc8",
            accent="#268bd2",
            bright="#2aa198",
            red="#dc322f",
            orange="#cb4b16",
            yellow="#b58900",
            green="#859900",
            teal="#2aa198",
            blue="#268bd2",
            purple="#6c71c4",
            pink="#d33682",
            keyword="#859900",
        ),
        build(
            "github-light",
            "GitHub Light",
            "纯白底、标准的蓝/绿/红；最“中性办公”，几乎不会有人觉得难看。",
            dark=False,
            bg="#ffffff",
            surface="#f6f8fa",
            alt="#eaeef2",
            text="#1f2328",
            muted="#656d76",
            subtle="#57606a",
            border="#d0d7de",
            selection="#ddf4ff",
            accent="#0969da",
            bright="#0550ae",
            red="#cf222e",
            orange="#bc4c00",
            yellow="#9a6700",
            green="#1a7f37",
            teal="#1b7c83",
            blue="#0969da",
            purple="#8250df",
            pink="#bf3989",
            keyword="#cf222e",
        ),
    )
