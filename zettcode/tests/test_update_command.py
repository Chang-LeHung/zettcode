"""`zettcode update`: install the newest release from the command line, and only report what was confirmed."""

from __future__ import annotations

from pathlib import Path

import pytest

from zettcode import cli
from zettcode import update as update_module
from zettcode.update import read_state, update_program

COMMAND = ("uv", "tool", "upgrade", "zettcode")


@pytest.fixture(autouse=True)
def the_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update_module, "upgrade_command", lambda: COMMAND)


class Session:
    """What a run of the command saw and said, with the package manager and the index stood in for."""

    def __init__(self, tmp_path: Path, *, latest: str | None, status: int = 0, installed: str | None = None) -> None:
        self.said: list[str] = []
        self.ran: list[tuple[str, ...]] = []
        self.path = tmp_path / "update.json"

        def fetch() -> str:
            if latest is None:
                raise OSError("offline")
            return latest

        def run(command) -> int:
            self.ran.append(tuple(command))
            return status

        self.code = update_program(
            current="0.1.0",
            path=self.path,
            fetch=fetch,
            run=run,
            read_installed=lambda: installed,
            say=self.said.append,
        )

    @property
    def text(self) -> str:
        return "\n".join(self.said)


def test_a_newer_release_is_installed_and_the_confirmed_version_is_recorded(tmp_path: Path):
    session = Session(tmp_path, latest="0.2.0", installed="0.2.0")

    assert session.code == 0
    assert session.ran == [COMMAND]
    assert "updated 0.1.0 → 0.2.0" in session.text and "restart" in session.text
    assert read_state(session.path).installed == "0.2.0", "so the program does not offer it again"


def test_the_newest_release_runs_nothing(tmp_path: Path):
    session = Session(tmp_path, latest="0.1.0")

    assert session.code == 0 and session.ran == []
    assert "already the newest release (0.1.0)" in session.text
    assert not session.path.exists()


def test_an_unreachable_index_does_not_stop_the_package_manager_from_deciding(tmp_path: Path):
    session = Session(tmp_path, latest=None, installed="0.1.0")

    assert session.ran == [COMMAND]
    assert session.code == 0
    assert "nothing newer to install" in session.text


def test_a_failed_upgrade_says_so_and_how_to_run_it_by_hand(tmp_path: Path):
    session = Session(tmp_path, latest="0.2.0", status=2)

    assert session.code == 1
    assert "failed (exit status 2)" in session.text and "uv tool upgrade zettcode" in session.text
    assert not session.path.exists(), "nothing is recorded for an upgrade that did not happen"


def test_an_exit_status_of_zero_is_not_believed_when_the_version_did_not_change(tmp_path: Path):
    """`uv tool upgrade` says "Nothing to upgrade" with 0, and so does a pip whose index is behind."""
    session = Session(tmp_path, latest="0.2.0", installed="0.1.0")

    assert session.code == 1
    assert "still 0.1.0, not 0.2.0" in session.text
    assert not session.path.exists()


def test_an_install_that_cannot_be_read_back_is_reported_as_unconfirmed(tmp_path: Path):
    session = Session(tmp_path, latest="0.2.0", installed=None)

    assert session.code == 0
    assert "could not be read back" in session.text
    assert not session.path.exists(), "an unconfirmed install is not written down as one"


def test_the_command_line_names_the_subcommand():
    assert cli.parse_args(["update"]).command == "update"
    assert cli.parse_args([]).command is None
    assert cli.parse_args(["-w", ".", "-r", "abc"]).command is None


def test_main_runs_the_update_and_exits_with_its_status(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("sys.argv", ["zettcode", "update"])
    monkeypatch.setattr(update_module, "update_program", lambda: 3)
    monkeypatch.setattr(cli, "tune_collector", lambda: pytest.fail("no session is started to update"))

    with pytest.raises(SystemExit) as stopped:
        cli.main()

    assert stopped.value.code == 3
