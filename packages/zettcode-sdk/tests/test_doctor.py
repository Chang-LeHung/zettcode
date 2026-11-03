"""`zettcode doctor`: ask every configured model one question and say which of them answer."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from zettcode import cli, doctor
from zettcode import update as update_module
from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.doctor import Probe, diagnose, doctor_program, format_report, probe


def model(name: str, **options) -> ModelConfig:
    return ModelConfig(model=name, token="t", **options)


class Endpoint:
    """A stand-in for the providers: each model answers, fails or stays silent as its name says."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    async def __call__(self, selected: ModelConfig):
        self.asked.append(selected.model)
        if selected.model.startswith("bad"):
            raise RuntimeError("401 Unauthorized:\n  the token was revoked")
        if selected.model.startswith("slow"):
            await asyncio.sleep(5)
        return "ok", (12, 1)


def run(coroutine):
    return asyncio.run(coroutine)


def test_a_model_that_answers_is_ok_with_what_it_said_and_what_it_cost():
    result = run(probe(model("good"), ask=Endpoint()))

    assert result.ok and result.detail == "ok" and result.tokens == (12, 1)


def test_a_failure_is_reported_in_the_providers_words_on_one_line_and_never_raised():
    result = run(probe(model("bad-key"), ask=Endpoint()))

    assert not result.ok
    assert result.detail == "401 Unauthorized: the token was revoked"


def test_a_model_that_stays_silent_is_reported_after_the_timeout():
    result = run(probe(model("slow"), timeout=0.05, ask=Endpoint()))

    assert not result.ok and "no answer within 0.05 seconds" in result.detail


def test_every_model_is_asked_at_once_and_the_probes_keep_the_order_they_are_configured_in():
    endpoint = Endpoint()
    models = [model("slow-one"), model("good"), model("bad-key")]

    probes = run(diagnose(models, timeout=0.05, ask=endpoint))

    assert [item.model.model for item in probes] == ["slow-one", "good", "bad-key"]
    assert [item.ok for item in probes] == [False, True, False]
    assert sorted(endpoint.asked) == ["bad-key", "good", "slow-one"]


def test_a_very_long_explanation_is_cut_so_a_web_page_does_not_fill_the_screen():
    async def page(selected):
        raise RuntimeError("<html>" + "x" * 5000)

    result = run(probe(model("m"), ask=page))

    assert len(result.detail) <= doctor.DETAIL_LIMIT and result.detail.endswith("…")


def test_the_report_names_each_model_its_api_and_the_tally():
    probes = [
        Probe(model("good", display_model="Good"), True, 0.84, "ok", (12, 1)),
        Probe(model("bad", anthropic=True), False, 2.0, "401 revoked"),
    ]

    lines = format_report(probes)

    assert (
        lines[0].startswith("ok   Good") and "0.8s" in lines[0] and "chat" in lines[0] and "12 in / 1 out" in lines[0]
    )
    assert lines[1].startswith("FAIL bad") and "anthropic: 401 revoked" in lines[1]
    assert lines[-1] == "2 models checked: 1 answered, 1 did not"
    assert format_report(probes[:1])[-1] == "1 model checked: all answered"
    assert format_report([]) == ["no models are configured"]


def config_with(tmp_path: Path, *names: str) -> ZettCodeConfig:
    return ZettCodeConfig(workspace=tmp_path, store=tmp_path / "sessions", models=tuple(model(n) for n in names))


def test_the_command_exits_zero_only_when_every_model_answered(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ZETTCODE_CONFIG", str(tmp_path / "config.toml"))
    said: list[str] = []

    assert doctor_program(config_with(tmp_path, "good", "good-two"), ask=Endpoint(), say=said.append) == 0
    assert said[0].startswith("ZettCode ") and str(tmp_path / "config.toml") in said[0]
    assert said[-1] == "2 models checked: all answered"

    assert doctor_program(config_with(tmp_path, "good", "bad-key"), ask=Endpoint(), say=said.append) == 1


def test_a_real_provider_error_is_a_failed_probe_not_a_crash():
    """The default asker builds the real adapter: an unreachable endpoint must come back as a failure."""
    unreachable = ModelConfig(model="m", token="t", base_url="http://127.0.0.1:9/v1")

    result = run(probe(unreachable, timeout=20))

    assert not result.ok and result.detail


def test_the_subcommand_and_its_alias_parse():
    assert cli.parse_args(["doctor"]).command == "doctor"
    assert cli.parse_args(["upgrade"]).command == "update", "upgrade is update by another name"
    assert cli.parse_args(["update"]).command == "update"


def test_main_runs_doctor_and_exits_with_its_status(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr("sys.argv", ["zettcode", "doctor"])
    config = config_with(tmp_path, "good")
    monkeypatch.setattr(cli, "resolve_config", lambda: config)
    monkeypatch.setattr(doctor, "doctor_program", lambda given: 4 if given is config else 0)
    monkeypatch.setattr(cli, "tune_collector", lambda: pytest.fail("no session is started to check the models"))

    with pytest.raises(SystemExit) as stopped:
        cli.main()

    assert stopped.value.code == 4


def test_main_runs_the_update_for_upgrade_too(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("sys.argv", ["zettcode", "upgrade"])
    monkeypatch.setattr(update_module, "update_program", lambda: 5)
    monkeypatch.setattr(cli, "tune_collector", lambda: pytest.fail("no session is started to update"))

    with pytest.raises(SystemExit) as stopped:
        cli.main()

    assert stopped.value.code == 5


def test_doctor_is_a_subcommand_only_and_no_slash_command_of_that_name_exists():
    from test_zettcode_app import rows_and_commands

    assert "doctor" not in {command.name for command in rows_and_commands().commands}
