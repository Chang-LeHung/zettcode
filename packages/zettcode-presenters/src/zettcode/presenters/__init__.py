"""The conversation's rows and how the terminal draws them.

`entries` is the data — one class per kind of row a transcript can hold — and `presenters` is how one kind becomes
lines: a presenter per kind, a presenter per tool name, and the generic `ToolPresenter` that catches any tool no
name claimed. `brand` is the pixel art the welcome row draws; `labels`, `statusline` and `rows` are the shell's
header, status and turn-line, published as the `shell`/`turn-line` entry points.

The terminal's transcript, the projector that fills it and the replay that rebuilds it stay in `zettcode.app`: this
distribution is the part of them that a plugin replaces — a front end registers its own presenter through
`ctx.tui.register_presenter`, and `zettcode-plugin-api` re-exports `Entry` and `Presenter` so it can.

The plugin that registers the presenters is `zettcode.presenters.plugin`, published as the `presenters` entry point.
`shell` and `turn-line` are entry points of this distribution too; all are discovered, and the terminal names the
ones it cannot run without in `REQUIRED_PLUGINS`.
"""

from __future__ import annotations
