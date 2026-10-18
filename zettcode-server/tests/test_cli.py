"""The ``zettcode-server`` command: what the arguments mean, and that serving wires them to the app."""

from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path

import pytest

from zettcode_server import __version__
from zettcode_server.cli import build_parser, main, settings_from, version_text


def test_the_version_names_the_server_and_the_agent_it_serves():
    text = version_text()

    assert text.startswith(f"zettcode-server {__version__}")
    assert "(zettcode " in text


def test_the_defaults_serve_the_current_directory_on_loopback_denying_shell_commands():
    settings = settings_from([])

    assert settings.workspace == Path.cwd().resolve()
    assert settings.host == "127.0.0.1" and settings.port == 3290
    assert settings.permission == "deny"
    assert settings.log_level == "info"
    assert settings.token is None


def test_the_token_defaults_to_the_environment_variable(monkeypatch):
    monkeypatch.setenv("ZETTCODE_SERVER_TOKEN", "s3cret")

    assert settings_from([]).token == "s3cret"
    assert settings_from(["--token", "given"]).token == "given"


def test_everything_the_arguments_name_reaches_the_settings(tmp_path: Path):
    config = tmp_path / "config.toml"
    settings = settings_from(
        [
            "-w",
            str(tmp_path),
            "--host",
            "0.0.0.0",
            "--port",
            "9001",
            "--permission",
            "safe",
            "--model",
            "fast",
            "--effort",
            "low",
            "--config",
            str(config),
            "--log-level",
            "debug",
        ]
    )

    assert settings.workspace == tmp_path.resolve()
    assert (settings.host, settings.port) == ("0.0.0.0", 9001)
    assert (settings.permission, settings.model, settings.effort) == ("safe", "fast", "low")
    assert settings.config_path == config
    assert settings.log_level == "debug"
    assert settings.url == "http://0.0.0.0:9001"


def test_an_ipv6_host_is_written_in_brackets_in_the_url():
    settings = settings_from(["--host", "::1"])

    assert settings.url == "http://[::1]:3290"


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["--port", "0"], "port"),
        (["--port", "70000"], "port"),
        (["--workspace", "/no/such/directory"], "no such directory"),
        (["--permission", "maybe"], "invalid choice"),
    ],
)
def test_arguments_that_cannot_work_stop_before_a_socket_is_opened(arguments, message, capsys):
    with pytest.raises(SystemExit) as stopped:
        settings_from(arguments)

    said = capsys.readouterr()
    # argparse's own refusals go to stderr; ours are the SystemExit message, which the shell prints.
    assert message in said.err + said.out + str(stopped.value.code)
    assert "Traceback" not in said.err


def test_help_exits_without_importing_fastapi_or_the_agent():
    """The command that explains the program must not load the server it explains."""
    script = (
        "import sys; from zettcode_server.cli import main; "
        "sys.argv = ['zettcode-server', '--help'];\n"
        "try:\n    main()\nexcept SystemExit:\n    pass\n"
        "print('fastapi' in sys.modules, 'zettcode.sdk' in sys.modules)\n"
    )

    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=120)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "False False"


def test_serving_builds_the_app_and_hands_it_to_uvicorn(monkeypatch, tmp_path: Path):
    served: dict[str, object] = {}

    def fake_run(app: object, **options: object) -> None:
        served["app"] = app
        served.update(options)

    monkeypatch.setitem(sys.modules, "uvicorn", types.SimpleNamespace(run=fake_run))
    monkeypatch.setattr("zettcode_server.app.create_app", lambda settings: ("app for", settings.workspace))

    main(["-w", str(tmp_path), "--port", "9100", "--log-level", "warning"])

    assert served["app"] == ("app for", tmp_path.resolve())
    assert served["host"] == "127.0.0.1" and served["port"] == 9100
    assert served["log_level"] == "warning"


def test_the_parser_is_what_help_describes():
    parser = build_parser()

    text = parser.format_help()

    assert "Serve the ZettCode coding agent over HTTP" in text
    assert "--workspace" in text and "--token" in text and "--permission" in text
    assert "deny" in text and "safe" in text
