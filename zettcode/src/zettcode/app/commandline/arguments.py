"""What the words after a program's name can be, for the programs whose arguments are not paths.

``git st`` is not a file name. A shell knows that because the shell's completion scripts know ``git``; this program
does not run those, so the knowledge a Tab needs lives here, one :class:`ArgumentCompleter` per program. The
completer for the whole line (:class:`~zettcode.app.commandline.ShellCompleter`) asks the one that claims the program
and falls back to paths and to the reader's own history when none does, which is all most programs need.

Adding a program is adding a subclass and naming it in :data:`ARGUMENTS`; nothing else knows which programs have
one.
"""

from __future__ import annotations

import subprocess
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from zettcode.tui import CompletionItem
from zettcode.tui.widgets.console import COMMAND, REFERENCE

#: Seconds a helper program (``git``) may take to answer before the Tab goes on without it.
TIMEOUT = 2.0

#: Candidates one source offers at most.
LIMIT = 200


@dataclass(frozen=True, slots=True)
class Suggestions:
    """What a program's completer offers for one word.

    Attributes:
        items: The candidates, already filtered to the word typed.
        exclusive: The slot takes nothing else: a path would be wrong here (the word after ``git`` is a subcommand),
            so none is offered beside these.
    """

    items: list[CompletionItem] = field(default_factory=list)
    exclusive: bool = False


class ArgumentCompleter(ABC):
    """The completion of one program's arguments.

    Attributes:
        commands: The program names this completer answers for.
    """

    commands: tuple[str, ...] = ()

    @abstractmethod
    def suggest(self, words: Sequence[str], prefix: str, cwd: Path) -> Suggestions | None:
        """Return the candidates for the word being typed, or ``None`` when this completer has nothing to say.

        Args:
            words: The words already typed in this command, the program first (``["git", "checkout"]``).
            prefix: The word being typed, which may be empty.
            cwd: The directory the command will run in.
        """


def matching(names: Sequence[str], prefix: str, kind: str) -> list[CompletionItem]:
    """Return the names that begin with ``prefix`` ignoring case, those that begin with it exactly as typed first."""
    folded = prefix.casefold()
    found = [name for name in names if name.casefold().startswith(folded)]
    found.sort(key=lambda name: not name.startswith(prefix))
    return [CompletionItem(value=name, type=kind) for name in found[:LIMIT]]


class GitArguments(ArgumentCompleter):
    """git: the subcommands it has (aliases included), and the branches, tags and remotes the ones that take them.

    The subcommands come from ``git --list-cmds``, so a newer git, a user's own ``alias.*`` and a ``git-foo`` on ``PATH``
    are all there without this list knowing them. A name is only offered where git expects one: before the first
    word that is not an option.
    """

    commands = ("git",)

    #: Subcommands whose arguments are, or may be, a branch, a tag or a commit-ish.
    TAKES_REFS = frozenset(
        {
            "branch",
            "checkout",
            "cherry-pick",
            "diff",
            "fetch",
            "log",
            "merge",
            "pull",
            "push",
            "rebase",
            "reset",
            "restore",
            "revert",
            "show",
            "switch",
            "tag",
        }
    )

    def __init__(self) -> None:
        self._subcommands: list[str] | None = None

    def suggest(self, words: Sequence[str], prefix: str, cwd: Path) -> Suggestions | None:
        """Offer subcommands in the first slot and references after a subcommand that takes them."""
        if prefix.startswith("-"):
            return None
        positional = self._positional(words[1:])
        if not positional:
            return Suggestions(matching(self._commands(cwd), prefix, COMMAND), exclusive=True)
        if positional[0] in self.TAKES_REFS:
            return Suggestions(matching(self._references(cwd), prefix, REFERENCE))
        return None

    @staticmethod
    def _positional(arguments: Sequence[str]) -> list[str]:
        """Return the arguments that are not options, nor the value of the two options that take one before the subcommand."""
        found: list[str] = []
        skip = False
        for argument in arguments:
            if skip:
                skip = False
            elif argument in ("-C", "-c") and not found:
                skip = True
            elif not argument.startswith("-"):
                found.append(argument)
        return found

    def _commands(self, cwd: Path) -> list[str]:
        """Return git's subcommands, asked for once and kept."""
        if self._subcommands is None:
            # The ones a person types first, then the aliases, then the rest of what git offers by name.
            groups = "list-mainporcelain,others,alias,nohelpers"
            self._subcommands = run_git(cwd, f"--list-cmds={groups}") or run_git(
                cwd, "--list-cmds=main,alias,nohelpers"
            )
        return self._subcommands

    @staticmethod
    def _references(cwd: Path) -> list[str]:
        """Return the branches, remote branches and tags of the repository the command will run in."""
        names = run_git(cwd, "for-each-ref", "--format=%(refname:short)", "refs/heads", "refs/remotes", "refs/tags")
        return [name for name in names if not name.endswith("/HEAD")]


def run_git(cwd: Path, *arguments: str) -> list[str]:
    """Run ``git`` and return the lines it printed; empty when git is missing, slow, or this is not a repository."""
    try:
        done = subprocess.run(
            ["git", *arguments],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return [line for line in done.stdout.splitlines() if line] if done.returncode == 0 else []


#: The programs whose arguments are known, as the completer for a line consults them.
ARGUMENTS: tuple[type[ArgumentCompleter], ...] = (GitArguments,)
