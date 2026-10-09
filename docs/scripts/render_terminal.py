"""Render a deterministic, offline conversation with the real TUI into SVG.

Run from the repository root with ``uv run python docs/scripts/render_terminal.py``.
The generated image is shared by the README and the documentation homepage.
No model is started, and all session files stay in a temporary directory.
"""

from __future__ import annotations

import argparse
import os
import tempfile
from dataclasses import replace
from html import escape
from pathlib import Path

from zettcode.app.agent.agent import ZettCodeAgent
from zettcode.app.agent.runtime import ZettCodeRuntime
from zettcode.app.brand import LOGO_PALETTE, LOGO_PIXELS
from zettcode.app.ui.app import ZettCodeApp
from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.plugins.builtins import ShellRows
from zettcode.plugins.loader import load_plugins
from zettcode.plugins.state import ShellContext
from zettcode.tui import DARK, HEADER, Canvas


class PreviewRows(ShellRows):
    """Keep the real header presentation but never expose a temporary path."""

    def render_header_left(self, context: ShellContext) -> str:
        """Show the illustrative workspace instead of its temporary directory."""
        return f"  {HEADER} zettcode  ~/projects/api"


def preview() -> Canvas:
    """Paint one sample conversation without a terminal, network, or user store."""
    previous = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="zettcode-docs-") as directory:
        try:
            workspace = Path(directory)
            config = ZettCodeConfig(
                workspace=workspace,
                store=workspace / "sessions",
                models=(ModelConfig(model="example-model", display_model="Your model", token="example-token"),),
                plugins_enabled=False,
                skills_enabled=False,
                mcp_enabled=False,
            )
            runtime = ZettCodeRuntime.preview(config)
            runtime.plugins = load_plugins(config, builtins=(PreviewRows(),))
            app = ZettCodeApp(ZettCodeAgent(runtime), theme=replace(DARK, background="#232a2e"))
            clock = [0.0]
            app.transcript.clock = lambda: clock[0]
            transcript = app.transcript
            transcript.begin_turn("Add limit/offset pagination to GET /users, and cover it with a test.")
            transcript.start_thinking()
            transcript.append_thinking("I’ll check the route and tests, then add validated pagination.")
            clock[0] = 1.2
            transcript.complete_thinking()
            for call_id, tool, arguments, output in (
                ("read", "read_file", {"path": "src/api/users.py"}, ""),
                ("edit", "replace_in_file", {"path": "src/api/users.py"}, ""),
                ("test", "run_shell", {"command": "pytest tests/test_users.py -q"}, "6 passed in 0.24s"),
            ):
                transcript.start_tool(call_id, tool, arguments)
                clock[0] += 1.0
                transcript.complete_tool(call_id, output, wait=False)
            transcript.append_answer(
                "Added pagination to **GET /users**.\n\n"
                "- `limit` defaults to 20 and is capped at 100.\n"
                "- `offset` starts at 0; both parameters are validated.\n"
                "- The response includes the total, so clients can page without counting.\n\n"
                "All six tests pass, including the new pagination checks."
            )
            transcript.settle_wait("Processed for 12s · 09:41")
            app._session_title = "Pagination for /users"
            app.app.resize(100, 40)
            app.app.mount()
            return app.app.render()
        finally:
            os.chdir(previous)


def svg(canvas: Canvas) -> str:
    """Serialize cell colours and glyphs without ANSI or external font assets."""
    cell_width, cell_height = 10, 20
    width, height = canvas.width * cell_width, canvas.height * cell_height
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" '
        'shape-rendering="crispEdges">',
        "<title>ZettCode — illustrative conversation rendered with the actual terminal widgets</title>",
        f'<rect width="{width}" height="{height}" fill="#232a2e"/>',
        '<g font-family="SFMono-Regular,Consolas,Liberation Mono,monospace" font-size="16" xml:space="preserve">',
    ]
    for row_index, row in enumerate(canvas.cells):
        for column, cell in enumerate(row):
            if cell.continuation:
                continue
            offset_x, offset_y = column * cell_width, row_index * cell_height
            style = cell.style
            if style.background and style.background != "#232a2e":
                parts.append(f'<rect x="{offset_x}" y="{offset_y}" width="10" height="20" fill="{style.background}"/>')
            if cell.character.strip():
                block = {
                    "█": (0, 0, 10, 20),
                    "▀": (0, 0, 10, 10),
                    "▄": (0, 10, 10, 10),
                    "▐": (5, 0, 5, 20),
                    "▌": (0, 0, 5, 20),
                }.get(cell.character)
                if block is not None:
                    left, top, block_width, block_height = block
                    parts.append(
                        f'<rect x="{offset_x + left}" y="{offset_y + top}" width="{block_width}" '
                        f'height="{block_height}" fill="{style.foreground or DARK.text}"/>'
                    )
                    continue
                weight = ' font-weight="700"' if style.bold else ""
                italic = ' font-style="italic"' if style.italic else ""
                parts.append(
                    f'<text x="{offset_x}" y="{offset_y + 16}" fill="{style.foreground or DARK.text}"{weight}{italic}>'
                    f"{escape(cell.character)}</text>"
                )
    parts.extend(("</g>", "</svg>"))
    return "\n".join(parts) + "\n"


def logo_svg() -> str:
    """Serialize the same square pixels as the terminal, with transparent margins."""
    pixel_size = 2
    offset_x = (32 - len(LOGO_PIXELS[0]) * pixel_size) // 2
    offset_y = (32 - len(LOGO_PIXELS) * pixel_size) // 2
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" fill="none" shape-rendering="crispEdges">',
        "<title>ZettCode pixel robot</title>",
    ]
    for pixel, colour in LOGO_PALETTE.items():
        paths: list[str] = []
        for row, pixels in enumerate(LOGO_PIXELS):
            column = 0
            while column < len(pixels):
                if pixels[column] != pixel:
                    column += 1
                    continue
                start = column
                while column < len(pixels) and pixels[column] == pixel:
                    column += 1
                length = (column - start) * pixel_size
                paths.append(
                    f"M{offset_x + start * pixel_size} {offset_y + row * pixel_size}h{length}v{pixel_size}h-{length}Z"
                )
        parts.append(f'<path d="{"".join(paths)}" fill="{colour}"/>')
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def main() -> None:
    """Write the preview and optional logo only to the selected asset paths."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("docs/public/terminal.svg"))
    parser.add_argument("--logo-output", type=Path, help="also regenerate the logo from the shared terminal pixel map")
    args = parser.parse_args()
    canvas = preview()
    args.output.write_text(svg(canvas), encoding="utf-8")
    if args.logo_output is not None:
        args.logo_output.write_text(logo_svg(), encoding="utf-8")


if __name__ == "__main__":
    main()
