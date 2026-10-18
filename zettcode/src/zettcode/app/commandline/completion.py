"""Tab completion for a command line: the first word is a program, the rest depend on the program.

:class:`ShellCompleter` is the :class:`~zettcode.tui.Completer` the command panel hands its line. In the position of a
command it offers the programs on ``PATH`` (and the commands the reader has used before, first). Anywhere else it
puts together, in this order, what the program is known to take (``git`` takes subcommands and branches, see
:mod:`~zettcode.app.commandline.arguments`), the word the reader typed there the last time they ran the same
command (``git st`` finds ``status`` in the history), and what is in the directory the word points into. It needs no
help from the shell the commands run in, which is what lets it behave the same for bash, zsh, fish and PowerShell
alike.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path

from zettcode.tui import Completer, CompletionItem
from zettcode.tui.widgets.console import ARGUMENT, COMMAND, DIRECTORY, EXECUTABLE, FILE, SYMLINK

from .arguments import ARGUMENTS, ArgumentCompleter

#: Candidates offered at most; a directory of ten thousand files must not become a menu of ten thousand.
LIMIT = 200

#: The words after which the next word is a command again (``sudo make``), besides the separators.
WRAPPERS = frozenset({"sudo", "time", "exec", "nohup", "xargs", "env", "command", "builtin", "then", "do", "else"})

#: The commands the panel itself understands, offered like programs.
INTERNAL = ("cd", "clear", "exit")

#: Programs after which only directories make sense.
DIRECTORY_ONLY = frozenset({"cd", "pushd", "rmdir"})


class ShellCompleter(Completer):
    """Complete the word under the cursor of a shell command.

    Args:
        cwd: The directory relative paths are read from; asked on every Tab because ``cd`` changes it.
        history: Commands typed before, oldest first. Their first words are offered ahead of the programs on
            ``PATH``, since what the reader has run is likelier than what is installed.
        path: ``PATH`` to search for programs; the environment's by default.
        home: What ``~`` stands for; the real home directory by default.
        arguments: The programs whose arguments are known; git by default.
    """

    def __init__(
        self,
        cwd: Callable[[], Path],
        history: Sequence[str] = (),
        *,
        path: str | None = None,
        home: Path | None = None,
        arguments: Sequence[ArgumentCompleter] | None = None,
    ) -> None:
        self.cwd = cwd
        self.history = tuple(history)
        self.path = os.environ.get("PATH", "") if path is None else path
        self.home = Path.home() if home is None else home
        self.arguments = tuple(kind() for kind in ARGUMENTS) if arguments is None else tuple(arguments)
        self._programs: list[str] | None = None

    def __call__(self, text: str, position: int) -> list[CompletionItem]:
        """Return the candidates for the word that ends at ``position``."""
        head = text[:position]
        start = len(head)
        while start > 0 and not head[start - 1].isspace():
            start -= 1
        word, before = head[start:], head[:start].rstrip()
        # A subshell or a group opens with a bracket that is part of the word, and stays when the name is completed.
        lead = word[: len(word) - len(word.lstrip("({"))]
        bare = word[len(lead) :]
        if self._is_command_position(before) and not bare.startswith(("~", ".", "/")) and "/" not in bare:
            return (
                [replace(item, value=lead + item.value, label=item.value) for item in self._programs_matching(bare)]
                if bare
                else []
            )
        words = self._words_of(before)
        return self._arguments_matching(words, word)

    # -- the first word -----------------------------------------------------
    @staticmethod
    def _is_command_position(before: str) -> bool:
        """Return whether the word being typed is where a program name goes."""
        if not before:
            return True
        if before.endswith(("|", ";", "&", "(", "{")):
            return True
        return before.split()[-1] in WRAPPERS

    @staticmethod
    def _words_of(before: str) -> list[str]:
        """Return the words of the command being typed, the program first: what follows the last separator and any ``sudo``."""
        for separator in ("|", ";", "&", "("):
            before = before.rpartition(separator)[2]
        words = before.split()
        while words and words[0] in WRAPPERS:
            words.pop(0)
        return words

    @classmethod
    def _command_of(cls, before: str) -> str:
        """Return the program the words before the cursor belong to."""
        words = cls._words_of(before)
        return words[0] if words else ""

    # -- the other words ----------------------------------------------------
    def _arguments_matching(self, words: list[str], word: str) -> list[CompletionItem]:
        """Return what can follow ``words``: the program's own arguments, then the history's, then paths.

        A word taken from the history stands in the order of use, and where the program's completer names the same
        word it is that one that is offered (it knows what the word is), only earlier. A word with a slash in it is
        a path and is not looked for in the history, which does not know where it was typed.
        """
        program = words[0] if words else ""
        known = next((c.suggest(words, word, self.cwd()) for c in self.arguments if program in c.commands), None)
        specific = known.items if known else []
        recalled = [] if program in DIRECTORY_ONLY or "/" in word else self._recalled(words, word)
        if known and known.exclusive:
            # The slot only takes what the program has: a typo that once ran is not a candidate.
            names = {item.value for item in specific}
            recalled = [value for value in recalled if value in names]
        paths = (
            [] if known and known.exclusive else self._paths_matching(word, directories_only=program in DIRECTORY_ONLY)
        )

        # A word from the history that is also something the program or the directory offers is that thing (a
        # directory keeps its slash and its colour), only earlier.
        known_by_name = {item.value.rstrip("/"): item for item in (*specific, *paths)}
        rank = {value: index for index, value in enumerate(recalled)}
        ordered = sorted(specific, key=lambda item: rank.get(item.value, len(rank)))
        ordered += [known_by_name.get(value) or CompletionItem(value=value, type=ARGUMENT) for value in recalled]
        ordered += paths
        unique: dict[str, CompletionItem] = {}
        for item in ordered:
            unique.setdefault(item.value, item)
        return list(unique.values())[:LIMIT]

    def _recalled(self, words: list[str], prefix: str) -> list[str]:
        """Return the words that followed ``words`` in earlier commands and begin with ``prefix``, newest first."""
        if not words:
            return []
        folded, depth = prefix.casefold(), len(words)
        found: dict[str, None] = {}
        for command in reversed(self.history):
            parts = command.split()
            if len(parts) > depth and parts[:depth] == words and parts[depth].casefold().startswith(folded):
                found.setdefault(parts[depth])
        return [name for name in found if name != prefix][:LIMIT]

    def _programs_matching(self, prefix: str) -> list[CompletionItem]:
        """Return the programs starting with ``prefix``, whatever the case: the reader's own first, then what is installed.

        A name that begins with the prefix exactly as typed comes ahead of one that matches only once case is ignored.
        """
        folded = prefix.casefold()
        names: dict[str, None] = {}
        for command in reversed(self.history):
            first = command.split(None, 1)[0] if command.strip() else ""
            if first.casefold().startswith(folded) and "/" not in first:
                names.setdefault(first)
        for name in (*INTERNAL, *self._installed()):
            if name.casefold().startswith(folded):
                names.setdefault(name)
        ordered = sorted(names, key=lambda name: not name.startswith(prefix))
        return [CompletionItem(value=name, type=COMMAND) for name in ordered[:LIMIT]]

    def _installed(self) -> list[str]:
        """Return the programs on ``PATH``, found once and kept."""
        if self._programs is not None:
            return self._programs
        found: dict[str, None] = {}
        extensions = (
            [e.lower() for e in os.environ.get("PATHEXT", ".EXE;.CMD;.BAT").split(";")] if os.name == "nt" else []
        )
        for directory in self.path.split(os.pathsep):
            try:
                with os.scandir(directory or ".") as entries:
                    for entry in entries:
                        try:
                            if not entry.is_file() or not os.access(entry.path, os.X_OK):
                                continue
                        except OSError:
                            continue
                        name = entry.name
                        if extensions:
                            stem, dot, extension = name.rpartition(".")
                            if not dot or f".{extension.lower()}" not in extensions:
                                continue
                            name = stem
                        found.setdefault(name)
            except OSError:
                continue
        self._programs = sorted(found)
        return self._programs

    # -- the other words ----------------------------------------------------
    def _paths_matching(self, word: str, *, directories_only: bool) -> list[CompletionItem]:
        """Return the entries of the directory ``word`` points into whose names start with what follows its last slash.

        The match ignores case, as a file browser's does (``read`` finds ``README.md``); directories are listed first,
        and within each group the names that match exactly as typed come before the ones that only match once case is
        ignored.
        """
        cut = max(word.rfind("/"), word.rfind("\\") if os.name == "nt" else -1)
        shown_dir, prefix = word[: cut + 1], word[cut + 1 :]
        folded = prefix.casefold()
        directory = self._resolve(shown_dir)
        try:
            with os.scandir(directory) as entries:
                listing = [(entry.name, *self._kind(entry)) for entry in entries]
        except OSError:
            return []

        def order(found: tuple[str, str, bool]) -> tuple[bool, bool, str]:
            return (not found[2], not found[0].startswith(prefix), found[0].casefold())

        items: list[CompletionItem] = []
        for name, kind, is_dir in sorted(listing, key=order):
            if not name.casefold().startswith(folded) or (name.startswith(".") and not prefix.startswith(".")):
                continue
            if directories_only and not is_dir:
                continue
            escaped = name.replace(" ", "\\ ")
            suffix = "/" if is_dir else ""
            items.append(CompletionItem(value=f"{shown_dir}{escaped}{suffix}", label=f"{name}{suffix}", type=kind))
            if len(items) >= LIMIT:
                break
        return items

    def _resolve(self, shown: str) -> Path:
        """Return the directory a typed prefix names: ``~`` is home, a relative one is under the working directory."""
        if not shown:
            return self.cwd()
        if shown.startswith("~"):
            shown = str(self.home) + shown[1:]
        path = Path(shown)
        return path if path.is_absolute() else self.cwd() / path

    @staticmethod
    def _kind(entry: os.DirEntry[str]) -> tuple[str, bool]:
        """Return what an entry is, as ``ls`` would colour it, and whether a path can go on through it.

        A link is its own kind whatever it points at, but one to a directory still takes the slash, because
        ``cd link/`` and ``ls link/`` go through it.
        """
        try:
            is_dir = entry.is_dir()
            if entry.is_symlink():
                return SYMLINK, is_dir
            if is_dir:
                return DIRECTORY, True
            if os.name == "nt":
                runnable = entry.name.lower().endswith((".exe", ".cmd", ".bat", ".com", ".ps1"))
            else:
                runnable = os.access(entry.path, os.X_OK)
            return (EXECUTABLE if runnable else FILE), False
        except OSError:
            return FILE, False
