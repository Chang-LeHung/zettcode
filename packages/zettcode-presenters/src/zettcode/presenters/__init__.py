"""The conversation's rows and how the terminal draws them.

`entries` is the data — one class per kind of row a transcript can hold — and `presenters` is how one kind becomes
lines: a presenter per kind, the families inside a kind (a tool, a change, a relayed message), and the registry that
picks between them. `brand` is the pixel art the welcome row draws.

The terminal's transcript, the projector that fills it and the replay that rebuilds it stay in `zettcode.app`: this
distribution is the part of them that a plugin replaces — a front end registers its own presenter through
`ctx.tui.register_presenter`, and `zettcode-plugin-api` re-exports `Entry` and `Presenter` so it can.

The plugin that registers the built-ins lives in the program (`zettcode.app.plugins.builtins`), because drawing a row
is a terminal hook and the terminal's plugin base is there; it reads `presenters.BUILTIN_PRESENTERS`, so the program
installs them the way it installs every other built-in — by listing it, never by discovering it — and `[plugins]
disable` has nothing to name.
"""

from __future__ import annotations
