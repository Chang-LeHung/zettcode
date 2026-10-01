"""Stable text snapshots so rendering changes show up as reviewable diffs.

The serializer never writes files: golden tests keep their expected block
inline, which keeps a test run from touching the checkout.
"""

from __future__ import annotations

from ..core.app import App
from ..core.theme import Theme
from ..core.widget import Widget
from ..render import DEFAULT_STYLE, Canvas, Style


def style_signature(style: Style) -> str:
    """Encode one style as a short, stable token list."""
    parts: list[str] = []
    if style.bold:
        parts.append("b")
    if style.italic:
        parts.append("i")
    if style.dim:
        parts.append("d")
    if style.reverse:
        parts.append("r")
    if style.foreground:
        parts.append(f"fg{style.foreground}")
    if style.background:
        parts.append(f"bg{style.background}")
    return ",".join(parts) if parts else "-"


def serialize(canvas: Canvas) -> str:
    """Render a canvas as trimmed text plus the styled runs that are not default."""
    rows = ["".join(cell.character for cell in row if not cell.continuation) for row in canvas.cells]
    text = "\n".join(row.rstrip() for row in rows)
    runs: list[str] = []
    for y, row in enumerate(canvas.cells):
        start = 0
        current = None
        for x, cell in enumerate(row):
            if cell.continuation:
                continue
            if cell.style != current:
                if current is not None and current != DEFAULT_STYLE:
                    runs.append(f"{y}:{start}-{x} {style_signature(current)}")
                start = x
                current = cell.style
        if current is not None and current != DEFAULT_STYLE:
            runs.append(f"{y}:{start}-{len(row)} {style_signature(current)}")
    if not runs:
        return text
    return text + "\n-- styles --\n" + "\n".join(runs)


def render_block(subject: Widget | App, *, width: int = 40, height: int = 8, theme: Theme | None = None) -> str:
    """Mount, lay out, and paint one frame, then return its snapshot block."""
    if isinstance(subject, App):
        app = subject
        app.resize(width, height)
    else:
        app = App(subject, width=width, height=height, theme=theme)
    app.mount()
    return serialize(app.render())
