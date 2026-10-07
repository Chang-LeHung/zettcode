"""The banner the shell writes into the transcript on startup.

It is data, not a widget: ``app.agent.transcript`` styles the mark and the
labels when it renders the ``welcome`` entry, so the text stays here and the
painting stays on the projector side.

The mark shares the website's silhouette: a small robot with two square eyes,
side ears, and a warm pixel heart. Block glyphs keep it sharp in a terminal.
"""

WELCOME = (
    "   ▄███████████▄\n"
    "  ▐█  ██   ██  █▌   ZettCode\n"
    "  ▐█    ▄ ▄    █▌   A focused coding agent\n"
    "   █    ▀█▀    █\n"
    "   ▀███████████▀\n"
    "\n"
    "  Type a task below, or /help for commands."
)
