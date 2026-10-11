"""Which commands the ``safe`` permission level may run without asking.

The classifier is fail-closed, so most of these tests are about what it refuses:
a wrong "yes" runs a command nobody approved, and a wrong "no" costs one keypress.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from zettcode.app.agent.readonly import is_read_only


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A real, quiet git repository."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


@pytest.mark.parametrize(
    "command",
    [
        "pwd",
        "ls",
        "ls -la src",
        "cat README.md",
        "head -n 20 src/zettcode/cli.py",
        "wc -l src/zettcode/cli.py",
        "grep -rn TODO .",
        'grep -rn "foo|bar" src',
        "grep -rn 'foo$' src",
        "echo hello",
        "diff a.txt b.txt",
        "jq .name package.json",
        "find . -name '*.py' -type f",
        "find src -maxdepth 2 -mtime -1 -print",
        "rg -n TODO src",
        "rg -n 'foo|bar' -g '*.py' src",
        "git status",
        "git status --short --branch",
        "git log --oneline -n 5",
        "git log --format=%H -n 3",
        "git diff",
        "git diff HEAD~1",
        "git diff HEAD^ --stat",
        "git show HEAD --name-only",
        "git blame -L 1,20 README.md",
        "git rev-parse --abbrev-ref HEAD",
        "git branch",
        "git branch --list 'feat/*'",
        "git branch -a",
        "git log --oneline | head -20",
        "cat README.md | wc -l",
    ],
)
def test_commands_that_only_read_are_recognised(command: str, repo: Path):
    assert is_read_only(command, repo) is True, command


@pytest.mark.parametrize(
    "command",
    [
        # Operators: each makes the shell do something other than run one program.
        "ls; rm x",
        "ls && rm x",
        "ls || rm x",
        "ls & rm x",
        "ls > out",
        "ls >> out",
        "cat < in",
        "ls 2>&1",
        "(ls)",
        "{ ls; }",
        "ls\nrm x",
        "ls\rrm x",
        "ls\trm x",
        "ls #; rm x",
        # Expansion: the shell would run something while building the words.
        "ls $(rm x)",
        "ls `rm x`",
        "echo $HOME",
        'echo "$HOME"',
        'echo "`id`"',
        'echo "a\\b"',
        'echo "hi!"',
        "echo ${HOME}",
        "ls \\; rm",
        # A pipe is allowed only between recognised programs, with nothing empty.
        "ls |",
        "| ls",
        "ls | | wc",
        "git status | sh",
        "cat f | xargs rm",
        # Not a plain program word.
        "./ls",
        "/bin/ls",
        "../bin/cat f",
        "LD_PRELOAD=/tmp/x ls",
        "PATH=/tmp ls",
        "=ls",
        "",
        "   ",
        # Programs that can write or run something, on purpose left off the list.
        "rm -rf x",
        "mv a b",
        "cp a b",
        "touch x",
        "mkdir x",
        "chmod +x f",
        "sed -i s/a/b/ f",
        "sed -n 1p f",
        "awk 'BEGIN{system(\"id\")}'",
        "sort -o out in",
        "sort in",
        "uniq in out",
        "tee out",
        "xargs ls",
        "env id",
        "sh -c id",
        "bash -c id",
        "python -c pass",
        "pytest",
        "make",
        "npm test",
        "curl http://example.com",
        "file -C",
        "cd src",
        "export A=b",
        # Not clean text outside quotes.
        "ls \u00e9",
        "ls \u2028",
        "ls \x00",
        "ls " + "a" * 5000,
    ],
)
def test_anything_else_is_not_read_only(command: str, repo: Path):
    assert is_read_only(command, repo) is False, repr(command)


def test_a_quote_that_never_closes_is_not_a_command():
    """An open quote runs to the end of the line, and what it swallows is unknown."""
    assert is_read_only("echo 'oops", None) is False
    assert is_read_only('echo "oops', None) is False


def test_quotes_make_an_operator_a_word_but_never_an_expansion():
    """`;` inside quotes is a character in a word; `$` inside double quotes is not."""
    assert is_read_only("echo 'a;b'", None) is True
    assert is_read_only('echo "a;b"', None) is True
    assert is_read_only("echo 'a$b'", None) is True
    assert is_read_only('echo "a$b"', None) is False


def test_every_character_the_shell_gives_a_meaning_is_refused_outside_quotes():
    """The allowed set is positive: a character not on it is not a plain word.

    Written as a sweep over every printable ASCII character so that a character
    added to the allowed set has to be added on purpose.
    """
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 _-./:=,+@%*?[]~^|'\"")
    for code in range(32, 127):
        char = chr(code)
        if char in allowed:
            continue
        assert is_read_only(f"ls a{char}b", None) is False, repr(char)
        assert is_read_only(f"ls {char}", None) is False, repr(char)


def test_the_program_word_is_read_after_the_quotes_come_off():
    """`'rm'` is `rm`: quoting a program name does not smuggle it past the list."""
    assert is_read_only("'ls'", None) is True
    assert is_read_only("'rm' x", None) is False
    assert is_read_only("r'm' x", None) is False
    assert is_read_only("''", None) is False


@pytest.mark.parametrize(
    "command",
    [
        "find . -exec rm {} ;",
        "find . -execdir rm x",
        "find . -ok rm x",
        "find . -delete",
        "find . -name x -fprint out",
        "find . -fprintf out x",
        "find . -fls out",
        "find . -name x -printf",
    ],
)
def test_find_may_match_and_print_but_not_act(command: str):
    assert is_read_only(command.replace("{}", "x").replace(" ;", ""), None) is False, command


@pytest.mark.parametrize(
    "command",
    [
        "rg --pre cat x",
        "rg --pre=cat x",
        "rg --pre-glob '*.gz' x",
        "rg --hostname-bin=x foo",
        "rg --search-zip foo",
        "rg -z foo",
        "rg -iz foo",
    ],
)
def test_rg_may_not_hand_a_file_to_a_program(command: str):
    assert is_read_only(command, None) is False, command


@pytest.mark.parametrize(
    "command",
    [
        # A global option before the subcommand can name a program to run.
        "git -c core.pager=sh log",
        "git -C /tmp status",
        "git --exec-path=/tmp status",
        "git --git-dir=/tmp/x status",
        # An option that writes a file or runs one.
        "git log --output=out",
        "git diff --output=out",
        "git diff --ext-diff",
        "git diff --textconv",
        "git grep -O foo",
        "git grep --open-files-in-pager=sh foo",
        # Git takes any unambiguous abbreviation of a long option, so a denylist
        # that names --output would not stop these; an allowlist does.
        "git log --outp=out",
        "git log --out=out",
        "git diff --ext-d",
        "git diff --ext",
        "git log --oneli",
        # Subcommands that change the repository, the network, or the index.
        "git commit -m x",
        "git add .",
        "git reset --hard",
        "git checkout main",
        "git push",
        "git pull",
        "git fetch",
        "git clean -fd",
        "git stash",
        "git config user.name x",
        "git remote add x y",
        "git tag v1",
        "git rebase main",
        "git",
        "git --version",
        # `git branch <name>` creates a branch; deleting and renaming are writes.
        "git branch feature",
        "git branch -d old",
        "git branch -D old",
        "git branch -m a b",
        "git branch -f main HEAD",
    ],
)
def test_git_is_trusted_only_for_whole_known_harmless_options(command: str, repo: Path):
    assert is_read_only(command, repo) is False, command


def test_git_needs_a_workspace_to_be_judged_in(tmp_path: Path):
    assert is_read_only("git status", None) is False
    assert is_read_only("git status", tmp_path) is False, "no repository here"


def test_git_is_not_trusted_in_a_repository_whose_config_names_a_program(repo: Path):
    """`core.fsmonitor`, `diff.external`, and a textconv driver run what they name.

    A model that can write files could write one and then ask for a harmless-looking
    `git status`; the config file is the tripwire for that.
    """
    config = repo / ".git" / "config"
    original = config.read_text(encoding="utf-8")
    assert is_read_only("git status", repo) is True

    for extra in (
        "[core]\n\tfsmonitor = /tmp/evil\n",
        "[diff]\n\texternal = /tmp/evil\n",
        '[diff "x"]\n\ttextconv = /tmp/evil\n',
        "[core]\n\tpager = /tmp/evil\n",
        "[core]\n\tsshCommand = /tmp/evil\n",
        "[core]\n\thooksPath = /tmp/evil\n",
        "[alias]\n\tst = !rm -rf x\n",
        "[include]\n\tpath = /tmp/evil\n",
        '[includeIf "gitdir:/"]\n\tpath = /tmp/evil\n',
    ):
        config.write_text(original + extra, encoding="utf-8")
        assert is_read_only("git status", repo) is False, extra
    config.write_text(original, encoding="utf-8")
    assert is_read_only("git status", repo) is True


def test_git_is_judged_by_the_repository_a_subdirectory_belongs_to(repo: Path):
    sub = repo / "pkg" / "inner"
    sub.mkdir(parents=True)
    assert is_read_only("git status", sub) is True

    (repo / ".git" / "config").write_text("[core]\n\tfsmonitor = x\n", encoding="utf-8")
    assert is_read_only("git status", sub) is False


def test_a_git_file_is_not_followed(tmp_path: Path):
    """A worktree's or submodule's `.git` points elsewhere, and this does not follow it."""
    (tmp_path / ".git").write_text("gitdir: /somewhere/else\n", encoding="utf-8")
    assert is_read_only("git status", tmp_path) is False


def test_the_read_only_programs_are_a_short_reviewed_list():
    """Adding a program here is a security decision; the list is pinned so that it is made on purpose."""
    from zettcode.app.agent import readonly

    assert readonly._PLAIN == frozenset(
        "pwd ls cat head tail wc stat du df which whoami id uname basename dirname realpath readlink echo grep diff cut jq".split()
    )
    # The ones left off for being able to write or run something are named, so a
    # careless "just add sed" fails this and not a code review.
    for dangerous in (
        "sed",
        "awk",
        "sort",
        "uniq",
        "tee",
        "xargs",
        "env",
        "sh",
        "bash",
        "python",
        "rm",
        "mv",
        "cp",
        "file",
    ):
        assert dangerous not in readonly._PLAIN
