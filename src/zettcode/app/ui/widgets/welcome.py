"""The banner the shell writes into the transcript on startup.

It is data, not a widget: ``app.agent.transcript`` styles the mark and the
labels when it renders the ``welcome`` entry, so the text stays here and the
painting stays on the projector side.
"""

WELCOME = (
    "     ╭─────┬─────╮\n"
    "     │     ✦     │   ZettCode\n"
    "     ╰─────┴─────╯   A focused coding agent\n"
    "\n"
    "  Type a task below, or /help for commands."
)
