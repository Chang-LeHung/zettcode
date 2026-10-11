"""Which shell commands cannot change anything, so the ``safe`` level may skip asking.

The question this answers is narrow and the answer is fail-closed: a command is
read-only only when every part of it is recognised, and anything this module does
not positively know is *not* read-only. A wrong "yes" runs something nobody
approved; a wrong "no" costs one keypress at the prompt — so the two errors are
not weighed equally, and every rule below leans the same way.

Three layers, each of which can only say no:

1. **Shape.** The command must be plain words joined by ``|``. The characters
   that make a shell do more than run a program — ``; & < > ( ) $ ` \\ { } !`` and
   newlines — are refused outside quotes, and ``$ ` \\ !`` inside double quotes,
   where the shell still expands them. A word is never *interpreted* here, only
   split and unquoted, so there is no expansion for a hostile string to hide in.
2. **Program.** The first word of each pipeline stage must equal a name on a
   short list of programs that have no way to write a file or run another
   program, or one of the three that need their arguments checked (``find``,
   ``rg``, ``git``). Equal, not similar: ``./ls`` is whatever the workspace says
   it is, and ``LD_PRELOAD=x ls`` is not ``ls``, and neither is on the list.
3. **Arguments.** For those three, an option is allowed only when it is known to
   be harmless. ``git`` takes options from an allowlist rather than a denylist
   because it accepts any unambiguous *abbreviation* of a long option: a denylist
   that names ``--output`` does not stop ``--outp``, an allowlist that names only
   whole, harmless options stops both.

What this does **not** do is make reading harmless. A read-only command can still
print a secret that sits in the workspace; ``safe`` is a promise that nothing will
change, not that nothing will be seen. And ``git`` reads its own configuration,
which can name programs to run (``core.fsmonitor``, ``diff.external``, a textconv
driver): the repository's config file is scanned for those keys, and a repository
that has any is treated as one ``git`` cannot be trusted in. The user's global git
configuration is not scanned.
"""

from __future__ import annotations

import re
from pathlib import Path

#: Characters that may appear outside quotes: letters, digits, space, and the
#: punctuation of paths, options, globs, and numbers. Everything else makes the
#: command something other than a plain word list, and is refused.
_UNQUOTED = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 _-./:=,+@%*?[]~^")

#: Characters a double-quoted string still expands, which a literal never does.
_EXPANDING = frozenset("$`\\!")

#: Programs with no way to write a file or run another program, whatever the
#: arguments. Each was checked for output-file options, ``-exec``-style options,
#: and a pager: ``sort -o``, ``uniq in out``, ``sed -i``/``w``/``e``, ``awk``'s
#: ``system``, ``tee``, ``xargs``, ``env``, and ``file -C`` are all left off for
#: exactly that reason.
_PLAIN = frozenset(
    {
        "pwd",
        "ls",
        "cat",
        "head",
        "tail",
        "wc",
        "stat",
        "du",
        "df",
        "which",
        "whoami",
        "id",
        "uname",
        "basename",
        "dirname",
        "realpath",
        "readlink",
        "echo",
        "grep",
        "diff",
        "cut",
        "jq",
    }
)

#: ``find`` primaries that only match or print. ``-exec``, ``-execdir``, ``-ok``,
#: ``-okdir``, ``-delete``, and the ``-fprint`` family are absent on purpose: an
#: option not on this list makes the command one that asks.
_FIND_OPTIONS = frozenset(
    {
        "-H",
        "-L",
        "-P",
        "-name",
        "-iname",
        "-path",
        "-ipath",
        "-wholename",
        "-regex",
        "-iregex",
        "-type",
        "-xtype",
        "-size",
        "-mtime",
        "-atime",
        "-ctime",
        "-mmin",
        "-amin",
        "-cmin",
        "-newer",
        "-maxdepth",
        "-mindepth",
        "-depth",
        "-empty",
        "-perm",
        "-user",
        "-group",
        "-nouser",
        "-nogroup",
        "-readable",
        "-writable",
        "-executable",
        "-links",
        "-inum",
        "-print",
        "-print0",
        "-prune",
        "-not",
        "-a",
        "-o",
        "-and",
        "-or",
        "-true",
        "-false",
        "-follow",
    }
)

#: Options of ``rg`` that run a program or read a compressed file through one.
_RG_FORBIDDEN = frozenset({"--pre", "--pre-glob", "--hostname-bin", "--search-zip"})

#: ``git`` subcommands that read the repository and nothing else.
_GIT_SUBCOMMANDS = frozenset(
    {
        "status",
        "log",
        "diff",
        "show",
        "blame",
        "ls-files",
        "ls-tree",
        "rev-parse",
        "rev-list",
        "describe",
        "shortlog",
        "cat-file",
        "merge-base",
        "name-rev",
        "show-ref",
        "diff-tree",
        "grep",
        "branch",
    }
)

#: Long options of those subcommands that are known to be harmless. Whole names
#: only: git accepts any unambiguous abbreviation of a long option, so a
#: shortened ``--outp`` is not here and therefore not allowed, which is the point.
_GIT_LONG_OPTIONS = frozenset(
    {
        "--oneline",
        "--graph",
        "--decorate",
        "--no-decorate",
        "--stat",
        "--shortstat",
        "--numstat",
        "--name-only",
        "--name-status",
        "--patch",
        "--no-patch",
        "--cached",
        "--staged",
        "--all",
        "--abbrev-commit",
        "--abbrev",
        "--no-color",
        "--color",
        "--short",
        "--long",
        "--branch",
        "--porcelain",
        "--untracked-files",
        "--ignored",
        "--format",
        "--pretty",
        "--date",
        "--since",
        "--until",
        "--after",
        "--before",
        "--author",
        "--committer",
        "--grep",
        "--max-count",
        "--skip",
        "--reverse",
        "--merges",
        "--no-merges",
        "--first-parent",
        "--follow",
        "--no-renames",
        "--word-diff",
        "--check",
        "--unified",
        "--raw",
        "--diff-filter",
        "--relative",
        "--no-ext-diff",
        "--no-textconv",
        "--summary",
        "--compact-summary",
        "--tags",
        "--heads",
        "--verify",
        "--show-current",
        "--list",
        "--remotes",
        "--verbose",
        "--abbrev-ref",
        "--symbolic-full-name",
        "--is-inside-work-tree",
        "--show-toplevel",
        "--count",
        "--line-number",
        "--files-with-matches",
        "--ignore-case",
        "--fixed-strings",
        "--extended-regexp",
        "--perl-regexp",
        "--word-regexp",
        "--invert-match",
        "--merged",
        "--no-merged",
        "--contains",
        "--no-contains",
    }
)

#: ``git`` config keys that name a program, and the words that make a config file
#: something other than a list of settings. Any of them in the repository's own
#: config means ``git`` there can run what the file says.
_GIT_CONFIG_TRIPWIRES = (
    "fsmonitor",
    "external",
    "textconv",
    "pager",
    "sshcommand",
    "hookspath",
    "askpass",
    "program",
    "helper",
    "alias",
    "command",
    "cmd",
    "include",
    "!",
)

_NUMBER_OPTION = re.compile(r"-\d+[A-Za-z]*$")


def is_read_only(command: str, workspace: Path | None = None) -> bool:
    """Return whether a shell command is recognised as unable to change anything.

    Args:
        command: The command line exactly as the model asked to run it.
        workspace: Directory the command runs in. ``git`` needs it, because it is
            only trusted when the repository's own config names no program to
            run; without it ``git`` is never read-only.

    Returns:
        ``True`` only when the whole command is understood and harmless; ``False``
        for everything else, including every command this module is unsure of.
    """
    stages = _split(command)
    if stages is None:
        return False
    return all(_stage_is_read_only(words, workspace) for words in stages)


def _split(command: str) -> list[list[str]] | None:
    """Split a command into pipeline stages of unquoted words, or ``None``.

    This is a scanner, not an interpreter: it walks the string once, tracking
    whether it is inside quotes, and it gives up the moment it meets anything it
    would have to *understand* — an operator, an expansion, a control character,
    a quote that does not close, or a character outside the allowed set.
    """
    if not command or len(command) > 4_000 or any(ord(char) < 32 or ord(char) == 127 for char in command):
        return None
    stages: list[list[str]] = [[]]
    word: list[str] | None = None
    quote = ""
    index = 0
    while index < len(command):
        char = command[index]
        index += 1
        if quote == "'":
            if char == "'":
                quote = ""
            else:
                word.append(char)  # type: ignore[union-attr]
            continue
        if quote == '"':
            if char == '"':
                quote = ""
            elif char in _EXPANDING:
                return None
            else:
                word.append(char)  # type: ignore[union-attr]
            continue
        if char == " ":
            if word is not None:
                stages[-1].append("".join(word))
                word = None
        elif char == "|":
            if index < len(command) and command[index] == "|":
                return None
            if word is not None:
                stages[-1].append("".join(word))
                word = None
            if not stages[-1]:
                return None
            stages.append([])
        elif char in "'\"":
            quote = char
            if word is None:
                word = []
        elif char in _UNQUOTED:
            if word is None:
                word = []
            word.append(char)
        else:
            return None
    if quote:
        return None
    if word is not None:
        stages[-1].append("".join(word))
    return stages if all(stages) else None


def _stage_is_read_only(words: list[str], workspace: Path | None) -> bool:
    """Judge one pipeline stage: its program, then the arguments that need a look."""
    # The program word has to *equal* a name on the list, which is the whole check
    # that `./ls` is not `ls` and `LD_PRELOAD=x ls` is not either: neither is equal
    # to anything on it, so neither needs a rule of its own.
    program, args = words[0], words[1:]
    if program in _PLAIN:
        return True
    if program == "find":
        return _find_is_read_only(args)
    if program == "rg":
        return _rg_is_read_only(args)
    if program == "git":
        return workspace is not None and _git_is_read_only(args, workspace)
    return False


def _find_is_read_only(args: list[str]) -> bool:
    """Allow ``find`` when every option it carries is a matching or printing one."""
    return all(arg in _FIND_OPTIONS or _NUMBER_OPTION.match(arg) for arg in args if arg.startswith("-"))


def _rg_is_read_only(args: list[str]) -> bool:
    """Allow ``rg`` unless an option hands a file to a program."""
    for arg in args:
        if arg == "--":
            break
        name = arg.split("=", 1)[0]
        if name in _RG_FORBIDDEN:
            return False
        if arg.startswith("-") and not arg.startswith("--") and "z" in arg:
            return False
    return True


def _git_is_read_only(args: list[str], workspace: Path) -> bool:
    """Allow a read-only ``git`` subcommand with known-harmless options.

    The subcommand must be the first word: anything before it is a global option
    such as ``-c`` or ``--exec-path``, which can name a program to run.
    """
    if not args or args[0] not in _GIT_SUBCOMMANDS:
        return False
    subcommand, rest = args[0], args[1:]
    options = []
    for arg in rest:
        if arg == "--":
            break
        if arg.startswith("--"):
            if arg.split("=", 1)[0] not in _GIT_LONG_OPTIONS:
                return False
            options.append(arg.split("=", 1)[0])
        elif arg.startswith("-") and len(arg) > 1:
            # ``-O`` hands ``git grep`` a pager to run; every other short option
            # reads.
            if "O" in arg:
                return False
            options.append(arg)
    if subcommand == "branch":
        # A bare name after ``git branch`` creates a branch, so a name is only
        # a pattern when ``--list`` says it is.
        positional = [arg for arg in rest if not arg.startswith("-")]
        if positional and "--list" not in options:
            return False
        if any(option in {"-d", "-D", "-m", "-M", "-c", "-C", "-u", "-f", "--force"} for option in options):
            return False
    return _git_config_is_inert(workspace)


def _git_config_is_inert(workspace: Path) -> bool:
    """Return whether the repository's own config names no program for git to run.

    The repository is found the way git finds it, by looking in each parent of the
    workspace in turn, so a shell started in a subdirectory is judged by the config
    of the repository it is in. A ``.git`` that is a file — a worktree or a
    submodule — points somewhere this does not follow, and is not inert.
    """
    for directory in (workspace, *workspace.parents):
        git = directory / ".git"
        try:
            if git.is_dir():
                text = (git / "config").read_text(encoding="utf-8", errors="replace").lower()
                return not any(word in text for word in _GIT_CONFIG_TRIPWIRES)
            if git.exists():
                return False
        except OSError:
            return False
    return False
