"""The command line behind `/bash`: shell histories, Tab completion, and running a command."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from zettcode.app.commandline import (
    BashHistory,
    CommandHistory,
    CommandPromptLauncher,
    CommandRunner,
    FishHistory,
    PlainHistory,
    PosixLauncher,
    PowerShellHistory,
    PowerShellLauncher,
    ShellCompleter,
    ShellLauncher,
    ZshHistory,
    detect_launcher,
)
from zettcode.app.commandline.history import preferred, read_tail
from zettcode.tui.widgets.console import COMMAND, DIRECTORY, EXECUTABLE, FILE, REFERENCE, SYMLINK

posix_only = pytest.mark.skipif(os.name == "nt", reason="needs a POSIX file system or shell")


# -- histories ---------------------------------------------------------------------------------------------


def test_bash_history_skips_the_time_stamps_it_writes_between_commands():
    text = "#1690000000\nls -la\n#1690000005\ngit status\n"

    assert list(BashHistory().parse(text)) == ["ls -la", "git status"]


def test_zsh_history_reads_extended_lines_plain_lines_and_commands_that_continue():
    text = ": 1690000000:0;ls -la\nplain command\n: 1690000010:2;echo one \\\ntwo\n: 1690000020:0;pwd\n"

    assert list(ZshHistory().parse(text)) == ["ls -la", "plain command", "echo one \ntwo", "pwd"]


def test_zsh_marks_its_own_control_bytes_and_they_are_taken_back():
    # 0x83 followed by 0xa0 stands for the single byte 0x80; here it is the middle of the UTF-8 for U+4F60.
    raw = b": 1:0;echo \xe4\x83\x9d\xa0\n"

    assert "\u4f60" in ZshHistory().decode(raw)


def test_fish_history_reads_the_cmd_of_each_entry_and_its_escapes():
    text = "- cmd: ls -la\n  when: 1690000000\n- cmd: echo a\\nb \\\\ c\n  when: 1690000001\n  paths:\n    - x\n"

    assert list(FishHistory().parse(text)) == ["ls -la", "echo a\nb \\ c"]


def test_powershell_history_joins_a_command_continued_with_a_backtick():
    text = "Get-ChildItem\nGet-Process `\n  -Name pwsh\nExit\n"

    assert list(PowerShellHistory().parse(text)) == ["Get-ChildItem", "Get-Process \n  -Name pwsh", "Exit"]


def test_the_file_zettcode_keeps_round_trips_a_newline_and_a_backslash(tmp_path: Path):
    history = CommandHistory(tmp_path / "own", sources=())

    history.record("echo a\nb")
    history.record("dir C:\\temp\\new")
    history.record("plain")

    assert history.load() == ["echo a\nb", "dir C:\\temp\\new", "plain"]
    assert (tmp_path / "own").read_text(encoding="utf-8").count("\n") == 3, "one line a command"


def test_every_source_finds_its_file_where_the_shell_keeps_it(tmp_path: Path):
    env = {"XDG_DATA_HOME": str(tmp_path / "data"), "APPDATA": str(tmp_path / "roaming")}

    assert list(BashHistory().paths(tmp_path, {"HISTFILE": "/x/h"})) == [Path("/x/h"), tmp_path / ".bash_history"]
    assert list(ZshHistory().paths(tmp_path, {})) == [tmp_path / ".zsh_history"]
    assert list(ZshHistory().paths(tmp_path, {"ZDOTDIR": "/z"}))[0] == Path("/z/.zsh_history")
    assert list(FishHistory().paths(tmp_path, env))[0] == tmp_path / "data" / "fish" / "fish_history"
    shell_paths = list(PowerShellHistory().paths(tmp_path, env))
    assert shell_paths[0].parts[-3:] == ("PowerShell", "PSReadLine", "ConsoleHost_history.txt")
    assert shell_paths[0].is_relative_to(tmp_path / "roaming")
    assert list(PlainHistory(tmp_path / "x").paths(tmp_path, {})) == [tmp_path / "x"]


def test_the_first_file_that_exists_is_the_one_read(tmp_path: Path):
    (tmp_path / ".bash_history").write_text("from home\n", encoding="utf-8")
    source = BashHistory()

    assert source.load(tmp_path, {"HISTFILE": str(tmp_path / "missing")}) == ["from home"]
    assert source.load(tmp_path / "nowhere", {}) == []


def test_history_in_the_wrong_encoding_keeps_the_commands_that_survive(tmp_path: Path):
    (tmp_path / ".bash_history").write_bytes(b"echo \xff\xfe broken\nls\n")

    assert BashHistory().load(tmp_path, {})[-1] == "ls"


def test_only_the_tail_of_a_huge_history_is_read_and_its_half_line_is_dropped(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("zettcode.app.commandline.history.TAIL_BYTES", 40)
    path = tmp_path / "history"
    path.write_text("".join(f"command number {n}\n" for n in range(100)), encoding="utf-8")

    raw = read_tail(path)

    assert raw is not None and len(raw) < 40
    lines = raw.decode().splitlines()
    assert lines[-1] == "command number 99" and all(line.startswith("command number") for line in lines)
    assert read_tail(tmp_path / "missing") is None


def test_the_shell_the_reader_uses_is_read_last_so_up_reaches_its_commands_first(tmp_path: Path):
    (tmp_path / ".bash_history").write_text("from bash\nshared\n", encoding="utf-8")
    (tmp_path / ".zsh_history").write_text(": 1:0;from zsh\n: 2:0;shared\n", encoding="utf-8")
    own = tmp_path / "own"

    as_zsh = CommandHistory(own, home=tmp_path, env={"SHELL": "/bin/zsh"}, platform="linux")
    as_bash = CommandHistory(own, home=tmp_path, env={"SHELL": "/bin/bash"}, platform="linux")

    assert as_zsh.load() == ["from bash", "from zsh", "shared"]
    assert as_bash.load() == ["from zsh", "from bash", "shared"]


def test_a_command_in_two_places_is_kept_once_at_its_newest_and_the_panels_own_come_last(tmp_path: Path):
    (tmp_path / ".bash_history").write_text("make\nls\n", encoding="utf-8")
    history = CommandHistory(tmp_path / "own", home=tmp_path, env={"SHELL": "/bin/bash"}, platform="linux")
    history.record("make")

    assert history.load() == ["ls", "make"]


def test_the_history_is_capped_and_a_file_that_cannot_be_written_is_not_an_error(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("zettcode.app.commandline.history.LIMIT", 3)
    (tmp_path / ".bash_history").write_text("".join(f"c{n}\n" for n in range(10)), encoding="utf-8")
    history = CommandHistory(tmp_path / "own", home=tmp_path, env={}, platform="linux")

    assert history.load() == ["c7", "c8", "c9"]
    blocked = CommandHistory(tmp_path / ".bash_history" / "impossible" / "own", home=tmp_path, env={})
    blocked.record("anything")  # the parent is a file: must not raise


@pytest.mark.parametrize(
    ("env", "platform", "expected"),
    [
        ({"SHELL": "/usr/bin/zsh"}, "linux", "zsh"),
        ({"SHELL": "/opt/homebrew/bin/fish"}, "darwin", "fish"),
        ({"SHELL": "/usr/local/bin/pwsh"}, "linux", "pwsh"),
        ({"SHELL": "C:\\Windows\\powershell.exe"}, "win32", "pwsh"),
        ({}, "win32", "pwsh"),
        ({}, "linux", "bash"),
        ({"SHELL": "/bin/tcsh"}, "linux", "bash"),
    ],
)
def test_the_readers_shell_is_what_shell_ends_in_else_the_platforms_own(env, platform, expected):
    assert preferred(env, platform) == expected


# -- completion ---------------------------------------------------------------------------------------------


def tree(root: Path) -> Path:
    (root / "src").mkdir(exist_ok=True)
    (root / "src" / "main.py").write_text("")
    (root / "docs").mkdir(exist_ok=True)
    (root / "my notes").mkdir(exist_ok=True)
    (root / "README.md").write_text("")
    (root / ".hidden").write_text("")
    (root / "run.sh").write_text("#!/bin/sh\n")
    if os.name != "nt":
        (root / "run.sh").chmod(0o755)
    return root


def complete(completer: ShellCompleter, text: str) -> list[str]:
    return [item.value for item in completer(text, len(text))]


def test_a_word_after_a_command_completes_to_the_entries_that_begin_with_it(tmp_path: Path):
    completer = ShellCompleter(lambda: tree(tmp_path), home=tmp_path)

    assert complete(completer, "cat R") == ["README.md", "run.sh"], "exactly as typed first, then the rest"
    assert complete(completer, "cat RE") == ["README.md"]
    assert complete(completer, "cat s") == ["src/"]
    assert complete(completer, "ls src/") == ["src/main.py"]


def test_matching_ignores_case_so_lower_case_finds_what_is_capitalised(tmp_path: Path):
    completer = ShellCompleter(lambda: tree(tmp_path), home=tmp_path)

    assert complete(completer, "cat read") == ["README.md"]
    assert complete(completer, "ls DO") == ["docs/"]


def test_a_name_that_matches_exactly_as_typed_comes_before_one_that_only_matches_ignoring_case(tmp_path: Path):
    for name in ("Readme", "readme.txt", "README2", "Other"):
        (tmp_path / name).write_text("")
    completer = ShellCompleter(lambda: tmp_path, home=tmp_path)

    assert complete(completer, "cat re") == ["readme.txt", "Readme", "README2"]
    assert complete(completer, "cat Re") == ["Readme", "readme.txt", "README2"]


def test_commands_match_ignoring_case_too_and_exact_case_leads(tmp_path: Path):
    completer = ShellCompleter(lambda: tmp_path, ["Git status", "gh pr"], path="", home=tmp_path)

    assert complete(completer, "gi") == ["Git"]
    assert complete(completer, "G") == ["Git", "gh"], "typed capital: the one that begins with it, then the rest"
    assert complete(completer, "g") == ["gh", "Git"]


def test_directories_come_first_and_hidden_names_wait_for_a_dot(tmp_path: Path):
    completer = ShellCompleter(lambda: tree(tmp_path), home=tmp_path)

    everything = complete(completer, "ls ")

    assert everything[:3] == ["docs/", "my\\ notes/", "src/"] and ".hidden" not in everything
    assert complete(completer, "ls .") == [".hidden"]


def test_a_name_with_a_space_is_offered_escaped(tmp_path: Path):
    completer = ShellCompleter(lambda: tree(tmp_path), home=tmp_path)

    (item,) = completer("cd my", 5)

    assert item.value == "my\\ notes/" and item.label == "my notes/"


def test_cd_offers_only_directories(tmp_path: Path):
    completer = ShellCompleter(lambda: tree(tmp_path), home=tmp_path)

    assert complete(completer, "cd ") == ["docs/", "my\\ notes/", "src/"]
    assert "README.md" in complete(completer, "ls R")


def test_a_tilde_means_home_and_an_absolute_path_is_read_where_it_points(tmp_path: Path):
    tree(tmp_path)
    completer = ShellCompleter(lambda: Path("/nonexistent"), home=tmp_path)

    assert complete(completer, "ls ~/sr") == ["~/src/"]
    assert complete(completer, f"ls {tmp_path}/do") == [f"{tmp_path}/docs/"]


def test_a_directory_that_cannot_be_read_offers_nothing(tmp_path: Path):
    completer = ShellCompleter(lambda: tmp_path, home=tmp_path)

    assert complete(completer, "ls no/such/di") == []


def test_the_first_word_completes_to_commands_the_reader_has_run_before_programs_on_path(tmp_path: Path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("gitk", "gzip"):
        program = bin_dir / (name + (".exe" if os.name == "nt" else ""))
        program.write_text("")
        if os.name != "nt":
            program.chmod(0o755)
    completer = ShellCompleter(lambda: tmp_path, ["gh pr list", "git status"], path=str(bin_dir), home=tmp_path)

    assert complete(completer, "g")[:2] == ["git", "gh"], "the newest history first"
    assert set(complete(completer, "g")) == {"git", "gh", "gitk", "gzip"}
    assert complete(completer, "gi") == ["git", "gitk"]
    assert complete(completer, "") == [], "nothing typed yet: a menu of every program would help nobody"


def test_the_words_of_the_panel_itself_are_offered_as_commands(tmp_path: Path):
    completer = ShellCompleter(lambda: tmp_path, path="", home=tmp_path)

    assert complete(completer, "cl") == ["clear"] and complete(completer, "ex") == ["exit"]


@pytest.mark.parametrize("line", ["ls | gi", "make && gi", "echo a; gi", "sudo gi", "(gi"])
def test_a_word_after_a_pipe_a_separator_or_sudo_is_a_command_again(tmp_path: Path, line):
    completer = ShellCompleter(lambda: tmp_path, ["git status"], path="", home=tmp_path)

    assert complete(completer, line) == ["(git" if line == "(gi" else "git"], "a bracket stays in front"


def test_an_argument_that_looks_like_a_command_is_still_a_path(tmp_path: Path):
    tree(tmp_path)
    completer = ShellCompleter(lambda: tmp_path, ["git status"], path="", home=tmp_path)

    assert complete(completer, "cat g") == []
    assert complete(completer, "cat ./s") == ["./src/"]


@posix_only
def test_each_candidate_says_what_it_is_so_the_strip_can_colour_a_directory_apart_from_a_file(tmp_path: Path):
    tree(tmp_path)
    (tmp_path / "link").symlink_to(tmp_path / "src")
    completer = ShellCompleter(lambda: tmp_path, ["rustc"], path="", home=tmp_path)

    kinds = {item.label: item.type for item in completer("ls ", 3)}

    assert kinds["src/"] == DIRECTORY and kinds["docs/"] == DIRECTORY
    assert kinds["link/"] == SYMLINK, "a link is its own kind, though it takes the slash"
    assert kinds["run.sh"] == EXECUTABLE and kinds["README.md"] == FILE
    assert {item.type for item in completer("ru", 2)} == {COMMAND}


def test_a_word_the_reader_typed_after_the_same_command_before_is_offered_for_any_program(tmp_path: Path):
    history = ["docker compose up", "docker ps -a", "kubectl get pods", "docker context ls"]
    completer = ShellCompleter(lambda: tmp_path, history, path="", home=tmp_path)

    assert complete(completer, "docker co") == ["context", "compose"], "the newest first"
    assert complete(completer, "docker CO") == ["context", "compose"], "whatever the case"
    assert complete(completer, "docker compose ") == ["up"]
    assert complete(completer, "kubectl g") == ["get"]
    assert complete(completer, "docker zzz") == []
    assert [item.type for item in completer("docker p", 8)] == ["argument"]


def test_a_word_of_the_history_is_dropped_for_cd_and_for_anything_that_is_a_path(tmp_path: Path):
    (tmp_path / "src").mkdir()
    completer = ShellCompleter(lambda: tmp_path, ["cd elsewhere", "cat old/file.txt"], path="", home=tmp_path)

    assert complete(completer, "cd e") == [], "the history does not know where it was typed"
    assert complete(completer, "cat old/") == []
    assert complete(completer, "cd s") == ["src/"]


def test_a_history_word_that_is_also_a_file_takes_the_kind_of_the_file(tmp_path: Path):
    (tmp_path / "notes").mkdir()
    completer = ShellCompleter(lambda: tmp_path, ["ls notes"], path="", home=tmp_path)

    (item,) = completer("ls no", 5)

    assert item.value == "notes/" and item.type == DIRECTORY


needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


def make_repository(root: Path) -> Path:
    def git(*arguments: str) -> None:
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *arguments],
            cwd=root,
            check=True,
            capture_output=True,
        )

    git("init", "-q")
    (root / "a.txt").write_text("a")
    git("add", ".")
    git("commit", "-q", "-m", "first")
    git("branch", "Feature-X")
    git("tag", "v1.0")
    return root


@needs_git
def test_the_word_after_git_is_one_of_its_subcommands_not_a_file(tmp_path: Path):
    make_repository(tmp_path)
    (tmp_path / "stuff.txt").write_text("")
    completer = ShellCompleter(lambda: tmp_path, ["git statt", "git status"], path="", home=tmp_path)

    found = complete(completer, "git st")

    assert "status" in found and "stash" in found
    assert "stuff.txt" not in found, "a subcommand slot takes no path"
    assert "statt" not in found, "a typo that once ran is not a candidate"
    assert found.index("status") < found.index("stash"), "the one the reader uses comes first"
    assert {item.type for item in completer("git st", 6)} == {COMMAND}
    # The case is ignored. Which commands share the prefix depends on the git that answers (`check-attr` and its
    # fellows are in some builds' "others" and not others'), so what is asserted is that the slot holds git's own names,
    # each of them a command beginning with what was typed, and nothing from the directory.
    found = complete(completer, "git CHECK")
    assert "checkout" in found, "whatever the case"
    assert all(name.casefold().startswith("check") and "." not in name for name in found), found
    assert "commit" in complete(completer, "git ") and "clone" in complete(completer, "git c")


@needs_git
def test_git_options_that_take_a_value_do_not_hide_the_subcommand_slot(tmp_path: Path):
    make_repository(tmp_path)
    completer = ShellCompleter(lambda: tmp_path, path="", home=tmp_path)

    assert "status" in complete(completer, "git -C . sta")
    assert "status" in complete(completer, "git --no-pager sta")
    assert "status" in complete(completer, "git -c core.pager=cat sta")


@needs_git
def test_git_checkout_and_the_like_offer_branches_tags_and_the_files_of_the_directory(tmp_path: Path):
    make_repository(tmp_path)
    (tmp_path / "feature.md").write_text("")
    completer = ShellCompleter(lambda: tmp_path, path="", home=tmp_path)

    found = {item.value: item.type for item in completer("git checkout fe", 14)}

    assert found["Feature-X"] == REFERENCE, "matched ignoring case"
    assert found["feature.md"] == FILE, "checkout takes files too"
    assert list(found).index("Feature-X") < list(found).index("feature.md"), "references first"
    assert complete(completer, "git switch v1") == ["v1.0"]
    assert "Feature-X" in complete(completer, "git log ") and "Feature-X" in complete(completer, "git branch -d ")
    assert complete(completer, "git add fea") == ["feature.md"], "add takes paths, not branches"


@needs_git
def test_outside_a_repository_git_offers_its_subcommands_and_no_references(tmp_path: Path):
    completer = ShellCompleter(lambda: tmp_path, path="", home=tmp_path)

    assert "status" in complete(completer, "git st")
    assert complete(completer, "git checkout zz") == []


def test_a_git_that_is_missing_or_hangs_offers_nothing_and_does_not_raise(tmp_path: Path, monkeypatch):
    def broken(*arguments, **options):
        raise FileNotFoundError("git")

    monkeypatch.setattr("zettcode.app.commandline.arguments.subprocess.run", broken)
    completer = ShellCompleter(lambda: tmp_path, path="", home=tmp_path)

    assert complete(completer, "git st") == []
    assert complete(completer, "git checkout x") == []


def test_other_programs_are_not_given_the_git_subcommands(tmp_path: Path):
    completer = ShellCompleter(lambda: tmp_path, path="", home=tmp_path)

    assert complete(completer, "gitk sta") == []
    assert complete(completer, "cat sta") == []


def test_a_program_can_have_a_completer_of_its_own(tmp_path: Path):
    from zettcode.app.commandline.arguments import ArgumentCompleter, Suggestions, matching

    class Make(ArgumentCompleter):
        commands = ("make",)

        def suggest(self, words, prefix, cwd):
            return Suggestions(matching(["build", "test", "Tidy"], prefix, "command"), exclusive=True)

    completer = ShellCompleter(lambda: tmp_path, path="", home=tmp_path, arguments=[Make()])

    assert complete(completer, "make t") == ["test", "Tidy"]
    assert complete(completer, "git t") == [], "the default git completer was replaced"


def test_a_path_with_an_empty_entry_and_a_missing_directory_is_searched_without_error(tmp_path: Path):
    completer = ShellCompleter(lambda: tmp_path, path=os.pathsep.join([str(tmp_path / "gone"), ""]), home=tmp_path)

    assert complete(completer, "zz") == []


# -- launching ----------------------------------------------------------------------------------------------


def test_a_unix_shell_is_run_with_dash_c():
    assert PosixLauncher("/bin/bash").argv("ls -la") == ["/bin/bash", "-c", "ls -la"]
    assert PosixLauncher("/usr/bin/zsh").argv("ls") == ["/usr/bin/zsh", "-c", "ls"]


def test_fish_is_started_without_its_configuration_because_loading_it_costs_a_second_per_command():
    """Measured with fish 4.0: `fish -c` 0.6-0.9 s with a real config.fish, `--no-config` 4 ms."""
    assert PosixLauncher("/opt/homebrew/bin/fish").argv("ls") == ["/opt/homebrew/bin/fish", "--no-config", "-c", "ls"]
    assert "--no-config" not in PosixLauncher("/bin/zsh").argv("ls")


def test_powershell_is_asked_for_utf8_and_no_profile_and_cmd_for_a_plain_c():
    argv = PowerShellLauncher("C:\\pwsh.exe").argv("Get-Date")

    assert argv[:4] == ["C:\\pwsh.exe", "-NoLogo", "-NoProfile", "-NonInteractive"]
    assert argv[-1].endswith("Get-Date") and "UTF8" in argv[-1]
    assert CommandPromptLauncher().argv("dir") == ["cmd.exe", "/d", "/c", "dir"]
    assert PowerShellLauncher("C:\\pwsh.exe").prompt == ">" and PosixLauncher("/bin/sh").prompt == "$"


def test_the_environment_asks_programs_for_colour_and_keeps_pagers_out_of_the_way():
    env = PosixLauncher("/bin/sh").environment({"HOME": "/h", "PAGER": "less"})

    assert env["HOME"] == "/h" and env["PAGER"] == "less", "the reader's own choices stand"
    assert env["FORCE_COLOR"] == "1" and env["CLICOLOR_FORCE"] == "1"
    assert env["CLICOLOR"] == "1", "BSD and macOS ls colour only when this is set as well"
    assert env["TERM"] == "xterm-256color" and env["GIT_PAGER"] == "cat"
    assert env["PY_COLORS"] == "1" and env["CARGO_TERM_COLOR"] == "always"


def test_git_is_told_to_colour_through_the_environment_since_it_reads_none_of_the_usual_variables():
    """Measured: with only FORCE_COLOR and CLICOLOR_FORCE set, `git status` into a pipe printed no colour at all."""
    env = PosixLauncher("/bin/sh").environment({})

    assert (env["GIT_CONFIG_COUNT"], env["GIT_CONFIG_KEY_0"], env["GIT_CONFIG_VALUE_0"]) == ("1", "color.ui", "always")


def test_git_settings_already_coming_through_the_environment_are_kept_and_this_one_goes_after_them():
    env = PosixLauncher("/bin/sh").environment(
        {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "user.name", "GIT_CONFIG_VALUE_0": "Ada"}
    )

    assert env["GIT_CONFIG_COUNT"] == "2" and env["GIT_CONFIG_KEY_0"] == "user.name"
    assert (env["GIT_CONFIG_KEY_1"], env["GIT_CONFIG_VALUE_1"]) == ("color.ui", "always")


def test_no_color_turns_all_of_it_off_and_a_variable_the_reader_set_keeps_their_value():
    quiet = PosixLauncher("/bin/sh").environment({"NO_COLOR": "1"})
    chosen = PosixLauncher("/bin/sh").environment({"FORCE_COLOR": "0", "CARGO_TERM_COLOR": "never"})

    assert not {"FORCE_COLOR", "CLICOLOR", "GIT_CONFIG_COUNT", "PY_COLORS"} & set(quiet)
    assert quiet["TERM"] == "xterm-256color", "the rest of the environment is still set"
    assert chosen["FORCE_COLOR"] == "0" and chosen["CARGO_TERM_COLOR"] == "never"


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
async def test_git_status_comes_out_coloured_through_a_real_pipe(tmp_path: Path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "new.txt").write_text("x")
    runner = CommandRunner(tmp_path, PythonLauncher())
    command = "import subprocess; subprocess.run(['git', 'status', '--short'])"

    _, output = await run(runner, command)

    assert "new.txt" in output and "\x1b[" in output


@posix_only
def test_launcher_detection_uses_the_shell_variable_when_it_takes_dash_c(tmp_path: Path):
    known = tmp_path / "zsh"
    odd = tmp_path / "tcsh"
    for shell in (known, odd):
        shell.write_text("")
        shell.chmod(0o755)

    assert detect_launcher({"SHELL": str(known)}, "darwin").shell == str(known)
    assert detect_launcher({"SHELL": "/no/such/zsh"}, "linux").name in {"bash", "sh"}
    assert detect_launcher({"SHELL": str(odd)}, "linux").name != "tcsh", "a shell not known to take -c"


def test_on_windows_the_launcher_is_powershell_7_then_windows_powershell_then_cmd(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "C:\\pwsh.exe" if name == "pwsh" else None)
    assert isinstance(detect_launcher({}, "win32"), PowerShellLauncher)
    monkeypatch.setattr("shutil.which", lambda name: "C:\\ps.exe" if name == "powershell" else None)
    assert detect_launcher({}, "win32").name == "ps"
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert isinstance(detect_launcher({"COMSPEC": "C:\\cmd.exe"}, "win32"), CommandPromptLauncher)


# -- running ------------------------------------------------------------------------------------------------


class PythonLauncher(ShellLauncher):
    """Runs the command text as Python, so a test needs no particular shell and means the same everywhere."""

    name = "python"

    def argv(self, command: str) -> list[str]:
        return [sys.executable, "-c", command]


def runner_in(directory: Path, **options) -> CommandRunner:
    options.setdefault("home", directory)
    return CommandRunner(directory, PythonLauncher(), **options)


async def run(runner: CommandRunner, command: str):
    output: list[str] = []
    result = await runner.run(command, output.append)
    return result, "".join(output)


async def until_output(output: list[str]) -> None:
    for _ in range(200):
        await asyncio.sleep(0.05)
        if output:
            return
    raise AssertionError("the command printed nothing")


async def test_the_output_of_a_command_arrives_with_its_exit_status(tmp_path: Path):
    result, output = await run(runner_in(tmp_path), "print('hello'); import sys; sys.exit(3)")

    assert output.strip() == "hello"
    assert result.code == 3 and result.text.startswith("exit 3") and not result.stopped


async def test_the_error_stream_comes_in_the_same_order_as_the_output(tmp_path: Path):
    _, output = await run(
        runner_in(tmp_path),
        "import sys; print('one', flush=True); print('two', file=sys.stderr, flush=True); print('three')",
    )

    assert output.split() == ["one", "two", "three"]


async def test_a_command_runs_in_the_directory_the_panel_is_in(tmp_path: Path):
    _, output = await run(runner_in(tmp_path), "import os; print(os.getcwd())")

    assert Path(output.strip()).resolve() == tmp_path.resolve()


async def test_output_arrives_while_the_command_is_still_running(tmp_path: Path):
    seen: list[str] = []
    runner = runner_in(tmp_path)

    task = asyncio.ensure_future(
        runner.run("import time; print('first', flush=True); time.sleep(2); print('last')", seen.append)
    )
    await until_output(seen)
    before_the_end = "".join(seen)
    result = await task

    assert "first" in before_the_end and "last" not in before_the_end
    assert result.code == 0


async def test_a_command_gets_no_input_so_a_prompt_ends_instead_of_waiting_for_a_key_nobody_can_press(tmp_path: Path):
    result, output = await run(runner_in(tmp_path), "input('name? ')")

    assert result.code != 0 and "EOFError" in output


async def test_the_environment_the_program_sees_asks_for_colour(tmp_path: Path):
    env = {key: value for key, value in os.environ.items() if key in {"PATH", "SYSTEMROOT"}}

    _, output = await run(
        runner_in(tmp_path, env=env),
        "import os; print(os.environ['FORCE_COLOR'], os.environ['CLICOLOR'], os.environ['TERM'])",
    )

    assert output.split() == ["1", "1", "xterm-256color"]


async def test_a_program_that_cannot_be_started_is_reported_not_raised(tmp_path: Path):
    class Missing(PythonLauncher):
        def argv(self, command):
            return [str(tmp_path / "no-such-program")]

    result, output = await run(CommandRunner(tmp_path, Missing()), "x")

    assert result.code is None and result.text == "not started" and "python" in output


async def test_cd_changes_the_directory_the_next_command_runs_in_and_dash_goes_back(tmp_path: Path):
    (tmp_path / "sub").mkdir()
    runner = runner_in(tmp_path)

    result, output = await run(runner, "cd sub")
    assert result.code == 0 and output == "" and runner.cwd == (tmp_path / "sub").resolve()
    _, here = await run(runner, "import os; print(os.getcwd())")
    assert Path(here.strip()).resolve() == (tmp_path / "sub").resolve()

    await run(runner, "cd -")
    assert runner.cwd == tmp_path.resolve()
    await run(runner, "cd ..")
    assert runner.cwd == tmp_path.resolve().parent
    await run(runner, "cd")
    assert runner.cwd == tmp_path.resolve(), "a bare cd goes home"
    await run(runner, "cd ~/sub")
    assert runner.cwd == (tmp_path / "sub").resolve()


async def test_cd_to_somewhere_that_is_not_there_says_so_and_stays_put(tmp_path: Path):
    runner = runner_in(tmp_path)

    result, output = await run(runner, "cd nowhere")
    assert result.code == 1 and "no such directory: nowhere" in output and runner.cwd == tmp_path

    _, quoted = await run(runner, 'cd "unbalanced')
    assert quoted.startswith("cd:") and runner.cwd == tmp_path
    _, many = await run(runner, "cd a b")
    assert "too many arguments" in many


async def test_cd_goes_to_a_directory_with_a_space_in_its_name(tmp_path: Path):
    (tmp_path / "my notes").mkdir()
    runner = runner_in(tmp_path)

    await run(runner, 'cd "my notes"')

    assert runner.cwd == (tmp_path / "my notes").resolve()


async def test_stopping_a_running_command_ends_it_and_says_it_was_stopped(tmp_path: Path):
    runner = runner_in(tmp_path, kill_after=1.0)
    output: list[str] = []

    task = asyncio.ensure_future(runner.run("import time; print('up', flush=True); time.sleep(60)", output.append))
    await until_output(output)
    assert runner.running and runner.stop() is True
    result = await asyncio.wait_for(task, 30)

    assert result.stopped and "stopped" in result.text
    assert not runner.running and runner.stop() is False, "nothing left to stop"


async def test_a_stop_in_the_moment_before_the_process_exists_is_not_lost(tmp_path: Path):
    """Ctrl-C right after Enter: nothing is running yet, but the reader has already asked for it to stop."""
    runner = runner_in(tmp_path, kill_after=2.0)

    task = asyncio.ensure_future(runner.run("import time; time.sleep(60)", lambda text: None))
    await asyncio.sleep(0)
    assert runner.stop() is True, "the start is in progress, so there is something to stop"
    result = await asyncio.wait_for(task, 30)

    assert result.stopped
    assert runner.stop() is False, "and once it has ended there is nothing"


STUBBORN = "import signal, time; signal.signal(signal.SIGINT, signal.SIG_IGN); print('up', flush=True); time.sleep(60)"


@posix_only
async def test_a_command_that_ignores_the_interrupt_is_killed_after_the_grace_period(tmp_path: Path):
    runner = runner_in(tmp_path, kill_after=0.3)
    output: list[str] = []

    task = asyncio.ensure_future(runner.run(STUBBORN, output.append))
    await until_output(output)
    started = time.monotonic()
    runner.stop()
    result = await asyncio.wait_for(task, 20)

    assert result.stopped and time.monotonic() - started < 10


@posix_only
async def test_a_second_stop_does_not_wait_for_the_grace_period(tmp_path: Path):
    runner = runner_in(tmp_path, kill_after=60)
    output: list[str] = []

    task = asyncio.ensure_future(runner.run(STUBBORN, output.append))
    await until_output(output)
    runner.stop()
    runner.stop()
    result = await asyncio.wait_for(task, 20)

    assert result.stopped


@posix_only
async def test_cancelling_the_run_does_not_leave_the_command_behind(tmp_path: Path):
    runner = runner_in(tmp_path)
    output: list[str] = []
    marker = tmp_path / "pid"
    script = (
        f"import os, time; open({str(marker)!r}, 'w').write(str(os.getpid())); print('up', flush=True); time.sleep(60)"
    )

    task = asyncio.ensure_future(runner.run(script, output.append))
    await until_output(output)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    pid = int(marker.read_text())
    for _ in range(100):
        try:
            os.kill(pid, 0)
        except OSError:
            break
        await asyncio.sleep(0.05)
    else:
        pytest.fail("the command outlived the run that started it")


async def test_a_flood_of_output_is_read_to_the_end_without_losing_a_line(tmp_path: Path):
    result, output = await run(runner_in(tmp_path), "print('\\n'.join(str(n) for n in range(20000)))")

    assert result.code == 0 and output.split() == [str(n) for n in range(20000)]


async def test_a_multibyte_character_split_between_two_reads_is_not_broken(tmp_path: Path):
    _, output = await run(
        runner_in(tmp_path),
        "import sys; sys.stdout.buffer.write(('\\u4f60' * 30000).encode()); sys.stdout.buffer.flush()",
    )

    assert output == "\u4f60" * 30000


@posix_only
async def test_a_real_shell_runs_a_pipeline(tmp_path: Path):
    runner = CommandRunner(tmp_path, PosixLauncher("/bin/sh"))

    result, output = await run(runner, "printf 'b\\na\\n' | sort")

    assert output.split() == ["a", "b"] and result.code == 0
