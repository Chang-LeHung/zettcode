"""Completion for the composer's slash commands, and their help text."""

from __future__ import annotations

from collections.abc import Sequence

from ....tui import Completer, CompletionItem
from ...commands import Command

KEY_HELP = (
    "  Enter send \u00b7 Alt-Enter newline \u00b7 Ctrl-C stop or clear\n"
    "  Ctrl-T thinking \u00b7 PgUp/PgDn scroll \u00b7 Ctrl-L redraw \u00b7 Ctrl-D exit"
)


class CommandCompleter(Completer):
    """Complete the slash commands matching the line the cursor sits on.

    A space ends the suggestion: ``/use abc`` has moved on to a session id, so
    the menu steps aside instead of filtering the commands down to nothing.
    """

    def __init__(self, commands: Sequence[Command]) -> None:
        """Keep the commands to offer; the shell builds them once at startup."""
        self.commands = tuple(commands)

    def __call__(self, text: str, position: int) -> tuple[CompletionItem, ...]:
        """Return the matching commands for the token ending at ``position``.

        Args:
            text: Full draft, newlines included.
            position: Cursor as a code-point index into ``text``.
        """
        start = text.rfind("\n", 0, position) + 1
        token = text[start:position]
        if not token.startswith("/") or any(character.isspace() for character in token):
            return ()
        return tuple(
            CompletionItem(command.name, description=command.description, type=command.type)
            for command in self.commands
            if command.name.startswith(token)
        )


def help_text(commands: Sequence[Command]) -> str:
    """Return the ``/help`` body as Markdown, generated from the command table."""
    rows = [f"- `{command.name}` \u2014 {command.description} (`{command.type}`)" for command in commands]
    return "\n".join(["**Commands**", *rows, "", "**Keys**", "", KEY_HELP])
