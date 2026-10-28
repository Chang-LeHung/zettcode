"""The ``zettcode-gateway`` command: its arguments become settings, and nothing outside a root is offered."""

from __future__ import annotations

from pathlib import Path

import pytest

from zettcode.gateway.cli import build_parser, settings_from, version_text
from zettcode.gateway.settings import TOKEN_VARIABLE


def test_with_no_token_there_is_no_sign_in_and_a_given_token_is_kept(tmp_path, monkeypatch):
    monkeypatch.delenv(TOKEN_VARIABLE, raising=False)

    made = settings_from(["-r", str(tmp_path)])
    given = settings_from(["-r", str(tmp_path), "--token", "abc"])

    assert made.open and made.token == "" and not given.open and given.token == "abc"
    assert made.host == "127.0.0.1" and made.allow_full is True and made.roots == (tmp_path.resolve(),)


def test_with_no_root_given_any_directory_may_be_chosen_and_no_full_turns_the_full_level_off(tmp_path, monkeypatch):
    monkeypatch.delenv(TOKEN_VARIABLE, raising=False)

    everywhere = settings_from([])
    limited = settings_from(["-r", str(tmp_path), "--no-full"])

    # The top of the drive the home directory is on: "/" on a POSIX machine, "C:\\" on a Windows one.
    assert everywhere.roots == (Path(Path.home().anchor or "/").resolve(),) and everywhere.allow_full is True
    assert limited.allow_full is False


def test_the_token_may_come_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv(TOKEN_VARIABLE, "from-env")

    settings = settings_from(["-r", str(tmp_path)])

    assert settings.token == "from-env" and not settings.open


def test_a_gateway_with_no_token_refuses_to_listen_beyond_this_machine(tmp_path, monkeypatch):
    monkeypatch.delenv(TOKEN_VARIABLE, raising=False)

    with pytest.raises(SystemExit) as refused:
        settings_from(["-r", str(tmp_path), "--host", "0.0.0.0"])

    assert "needs a token" in str(refused.value)
    assert settings_from(["-r", str(tmp_path), "--host", "0.0.0.0", "--token", "t"]).host == "0.0.0.0"


def test_a_root_that_is_not_a_directory_or_a_bad_port_stops_the_start(tmp_path):
    with pytest.raises(SystemExit):
        settings_from(["-r", str(tmp_path / "absent")])
    with pytest.raises(SystemExit):
        settings_from(["-r", str(tmp_path), "--port", "0"])


def test_help_and_version_answer_without_loading_the_app(capsys):
    assert version_text().startswith("zettcode-gateway ")
    assert "--no-full" in build_parser().format_help()
