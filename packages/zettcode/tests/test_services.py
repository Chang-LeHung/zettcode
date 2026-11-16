"""``zettcode start|stop|restart [broker|gateway|all]``: which steps run, and in what order."""

from __future__ import annotations

import pytest

from zettcode import services


def names(action: str, target: str) -> list[str]:
    return [step.__name__ for step in services.plan(action, target)]


def test_all_starts_the_broker_before_the_gateway_and_stops_it_after():
    assert names("start", "all") == ["_broker_start", "_gateway_start"]
    assert names("stop", "all") == ["_gateway_stop", "_broker_stop"]


def test_restart_all_takes_the_gateway_down_first_and_brings_it_up_last():
    assert names("restart", "all") == ["_restart_all"]


def test_one_target_runs_only_its_own_step():
    assert names("restart", "broker") == ["_broker_restart"]
    assert names("stop", "gateway") == ["_gateway_stop"]


def test_the_target_defaults_to_all_and_must_be_known():
    assert services.build_parser("start").parse_args([]).target == "all"
    with pytest.raises(SystemExit):
        services.build_parser("start").parse_args(["everything"])


def test_a_failed_step_ends_all_and_its_status_is_reported(monkeypatch):
    calls: list[str] = []

    def fail(assume_yes: bool) -> int:
        calls.append("first")
        return 1

    def after(assume_yes: bool) -> int:
        calls.append("second")
        return 0

    monkeypatch.setattr(services, "plan", lambda action, target: [fail, after])
    assert services.services_program("start", ["all"]) == 1
    assert calls == ["first"]


def _record(monkeypatch, *, broker_restart=0, gateway_stop=0):
    calls: list[tuple] = []
    monkeypatch.setattr(services, "_recorded", lambda: None)
    monkeypatch.setattr(services.gateway_cli, "settings_from", lambda argv, base=None: "settings")
    monkeypatch.setattr(
        services.gateway_cli,
        "stop",
        lambda directory, quiet=False: calls.append(("gateway.stop", quiet)) or gateway_stop,
    )
    monkeypatch.setattr(services.gateway_cli, "start", lambda settings: calls.append(("gateway.start", settings)) or 0)
    monkeypatch.setattr(
        services.broker_cli,
        "restart",
        lambda directory, companions, assume_yes=False: calls.append(("broker.restart", assume_yes)) or broker_restart,
    )
    monkeypatch.setattr(services.broker_cli, "stop", lambda directory: calls.append(("broker.stop",)) or 0)
    return calls


def test_restart_all_passes_yes_on_and_brings_the_gateway_back_with_its_settings(monkeypatch):
    calls = _record(monkeypatch)
    assert services.services_program("restart", ["all", "-y"]) == 0
    assert calls == [("gateway.stop", True), ("broker.restart", True), ("gateway.start", "settings")]


def test_restart_all_brings_the_gateway_back_even_when_the_broker_would_not_restart(monkeypatch):
    calls = _record(monkeypatch, broker_restart=1)
    assert services.services_program("restart", ["all"]) == 1
    assert calls[-1] == ("gateway.start", "settings")


def test_stop_all_stops_the_broker_even_when_the_gateway_could_not_be_identified(monkeypatch):
    calls = _record(monkeypatch, gateway_stop=1)
    assert services.services_program("stop", ["all"]) == 1
    assert ("broker.stop",) in calls


def test_a_service_word_after_a_global_option_is_refused_not_turned_into_a_session(monkeypatch):
    from zettcode import cli

    monkeypatch.setattr("sys.argv", ["zettcode", "-w", ".", "start"])
    monkeypatch.setattr("zettcode.broker.reload.check_in_background", lambda: None)
    with pytest.raises(SystemExit) as refused:
        cli.main()
    assert "put the word first" in str(refused.value)
