"""The banner the shell writes into the transcript on startup.

It is data, not a widget: ``app.agent.transcript`` styles the mark and the
labels when it renders the ``welcome`` entry, so the text stays here and the
painting stays on the projector side.

The mark is pixel art drawn with block glyphs — a small robot head — and the
old sparkle sits in the middle of its face. Its rows are shaded top-down, so
the reader sees a lit icon rather than a flat frame.
"""

WELCOME = (
    "  ▄███████▄\n"
    "  █ ██ ██ █   ZettCode\n"
    "  █   ✦   █   A focused coding agent\n"
    "  ▀███████▀\n"
    "\n"
    "  Type a task below, or /help for commands."
)
