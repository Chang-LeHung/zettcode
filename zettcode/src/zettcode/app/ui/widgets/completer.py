"""Completion for the composer's slash commands and ``@`` resources."""

from __future__ import annotations

import re
from collections.abc import Sequence

from zettcode.app.agent.dialogue.mentions import MentionRegistry
from zettcode.app.commands import Command
from zettcode.tui import SEPARATOR, Completer, CompletionItem

from .follow_up import OPTION

#: A draft's text before the word under the cursor, when that word is the one right after a command.
COMMAND_PREFIX = re.compile(r"(/\S+)[ \t]+")

KEY_HELP = (
    f"  Enter send {SEPARATOR} Shift-Enter or Alt-Enter newline {SEPARATOR} Ctrl-C stop or clear\n"
    f"  Ctrl-T thinking {SEPARATOR} PgUp/PgDn scroll {SEPARATOR} Alt-\u2191/\u2193 jump to a message\n"
    f"  Ctrl-L redraw {SEPARATOR} Ctrl-D exit\n"
    f"  While a request runs, Enter asks whether a message should steer it or follow up after it;\n"
    f"  {OPTION.capitalize()}-\u2191/\u2193 select a follow-up {SEPARATOR} \u2191/\u2193 move the highlight "
    f"{SEPARATOR} {OPTION.capitalize()}-\u2191/\u2193 reorder {SEPARATOR} Enter edit "
    f"{SEPARATOR} Del remove {SEPARATOR} Esc done"
)


class CommandCompleter(Completer):
    """Complete the slash commands, their first word, and ``@`` resources on the cursor's line.

    A leading ``/`` filters the commands; a leading ``@`` filters the resources
    the mention providers offer, skills among them. After a command that lists
    subcommands and a space, the menu offers those (``/config `` then ``add``,
    ``remove``, ...). Any further space ends the suggestion: ``/resume abc``
    has moved on to a session id, so the menu steps aside instead of filtering
    anything down to nothing.
    """

    def __init__(self, commands: Sequence[Command], mentions: MentionRegistry | None = None) -> None:
        """Keep the commands to offer; the shell builds them once at startup."""
        self.commands = tuple(commands)
        self.mentions = mentions

    def __call__(self, text: str, position: int) -> tuple[CompletionItem, ...]:
        """Return the matching commands for the token ending at ``position``.

        Args:
            text: Full draft, newlines included.
            position: Cursor as a code-point index into ``text``.
        """
        # The token is the run of non-space characters under the cursor, so an
        # ``@`` resource is still offered when it sits inside a sentence.
        start = position
        while start > 0 and not text[start - 1].isspace():
            start -= 1
        token = text[start:position]
        if token.startswith("@"):
            if self.mentions is None or any(character.isspace() for character in token):
                return ()
            return tuple(
                CompletionItem(mention.token, description=mention.description, type=mention.kind)
                for mention in self.mentions.candidates(token[1:])
            )
        if not token.startswith("/") or any(character.isspace() for character in token):
            return self._subcommands(text[:start], token)
        return tuple(
            CompletionItem(command.name, description=command.description, type=command.type)
            for command in self.commands
            if command.name.startswith(token)
        )

    def _subcommands(self, before: str, token: str) -> tuple[CompletionItem, ...]:
        """Return the words a command takes first, when the cursor is on the word right after its name.

        Only the second word of the draft is offered: ``before`` must be nothing but a command and the
        spaces after it. A word further on is the command's own argument (a session id, a model's
        settings), which the menu has no business filtering.
        """
        match = COMMAND_PREFIX.fullmatch(before)
        if match is None or any(character.isspace() for character in token):
            return ()
        command = next((command for command in self.commands if command.name == match.group(1)), None)
        if command is None:
            return ()
        return tuple(
            CompletionItem(
                option.name,
                description=" ".join(
                    part for part in (option.description, "(current)" if option.current else "") if part
                ),
                final=not option.needs_more,
                current=option.current,
            )
            for option in command.options()
            if option.name.startswith(token)
        )


def help_text(commands: Sequence[Command]) -> str:
    """Return the ``/help`` body as Markdown, generated from the command table."""
    rows = [f"- `{command.name}` \u2014 {command.description} (`{command.type}`)" for command in commands]
    return "\n".join(["**Commands**", *rows, "", "**Keys**", "", KEY_HELP])
