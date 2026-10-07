"""The banner the shell writes into the transcript on startup.

It is data, not a widget: ``WelcomeProcessor`` combines the shared pixel mark
with themed labels when it renders the ``welcome`` entry.

The compact mark retains the website's solid face, square eyes, side ears, and
warm heart. Its labels form one block next to it, instead of leaving the hint
detached underneath. Half blocks keep the pixels square in tall terminal cells.
"""

from ...brand import LOGO_LINES

WELCOME = "\n".join(
    f"  {line.text}"
    + {
        1: "   ZettCode",
        2: "   A focused coding agent",
        4: "   Type a task, or /help for commands.",
    }.get(index, "")
    for index, line in enumerate(LOGO_LINES)
)
