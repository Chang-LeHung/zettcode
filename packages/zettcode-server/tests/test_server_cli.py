"""The ``zettcode-server`` command: what the arguments mean, and that serving wires them to the app."""

from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path

import pytest

from zettcode.server.cli import build_parser, main, settings_from, version_text
from zettcode.version import __version__


def test_the_version_is_the_one_package_it_ships_in():
    text = version_text()

    assert text == f"zettcode-server {__version__}"


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
        "import sys; from zettcode.server.cli import main; "
        "sys.argv = ['zettcode-server', '--help'];\n"
        "try:\n    main()\nexcept SystemExit:\n    pass\n"
        "print('fastapi' in sys.modules, 'zettcode.sdk' in sys.modules)\n"
    )

    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=120)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "False False"


def test_serving_builds_the_app_and_hands_it_to_uvicorn(monkeypatch, tmp_path: Path):
    served: dict[str, object] = {}

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(app):
        served["started"] = True
        yield
        served["closed"] = True

    app = types.SimpleNamespace(router=types.SimpleNamespace(lifespan_context=lifespan))

    def config(app: object, **options: object):
        served["app"] = app
        served.update(options)
        return types.SimpleNamespace(setup_event_loop=lambda: served.update(loop_setup=True))

    class Server:
        def __init__(self, config):
            pass

        async def serve(self):
            assert served["started"]

    monkeypatch.setitem(sys.modules, "uvicorn", types.SimpleNamespace(Config=config, Server=Server))
    monkeypatch.setattr("zettcode.server.app.create_app", lambda settings: app)

    main(["-w", str(tmp_path), "--port", "9100", "--log-level", "warning"])

    assert served["app"] is app
    assert served["closed"] and served["lifespan"] == "off"
    assert served["loop_setup"]
    assert served["host"] == "127.0.0.1" and served["port"] == 9100
    assert served["log_level"] == "warning"


@pytest.mark.parametrize("failure", [None, RuntimeError, KeyboardInterrupt])
def test_cli_runs_real_app_lifespan_and_cleanup(monkeypatch, tmp_path, failure):
    import asyncio

    import uvicorn

    from zettcode.server.app import create_app
    from zettcode.server.runner import Runner

    events = []
    apps = []
    close = Runner.close

    def factory():
        events.append("started")
        return None

    def build(settings):
        app = create_app(settings, client_factory=factory)
        apps.append(app)
        return app

    async def closed(runner):
        await close(runner)
        events.append("closed")

    async def serve(server):
        assert events == ["started"]
        assert server.config.app is apps[0]
        assert server.config.lifespan == "off"
        assert apps[0].state.runner.maybe_client is None
        assert asyncio.get_running_loop().is_running()
        if failure is not None:
            raise failure("HTTP serve failed")

    monkeypatch.setattr("zettcode.server.app.create_app", build)
    monkeypatch.setattr(Runner, "close", closed)
    monkeypatch.setattr(uvicorn.Server, "serve", serve)
    if failure is RuntimeError:
        with pytest.raises(RuntimeError, match="HTTP serve failed"):
            main(["-w", str(tmp_path)])
    else:
        main(["-w", str(tmp_path)])
    assert events == ["started", "closed"]


def test_startup_configuration_failure_is_one_sentence(monkeypatch, tmp_path):
    from contextlib import asynccontextmanager

    from zettcode.sdk.errors import ConfigurationError

    @asynccontextmanager
    async def lifespan(app):
        raise ConfigurationError("Cannot inherit plugin 'backend': unavailable")
        yield  # pragma: no cover - async context-manager shape

    app = types.SimpleNamespace(router=types.SimpleNamespace(lifespan_context=lifespan))
    monkeypatch.setattr("zettcode.server.app.create_app", lambda settings: app)
    with pytest.raises(SystemExit) as stopped:
        main(["-w", str(tmp_path)])
    assert str(stopped.value) == "zettcode-server: Cannot inherit plugin 'backend': unavailable"


async def test_server_factory_propagates_inherited_configuration_failure(tmp_path):
    from zettcode.sdk.errors import ConfigurationError
    from zettcode.server.runner import Runner

    def factory():
        raise ConfigurationError("Cannot inherit plugin 'backend': unavailable")

    runner = Runner(settings_from(["-w", str(tmp_path)]), factory)
    with pytest.raises(ConfigurationError, match="Cannot inherit.*backend"):
        await runner.start()
    assert runner._client is None


def test_the_parser_is_what_help_describes():
    parser = build_parser()

    text = parser.format_help()

    assert "Serve the ZettCode coding agent over HTTP" in text
    assert "--workspace" in text and "--token" in text and "--permission" in text
    assert "deny" in text and "safe" in text


def test_the_harness_is_left_to_the_configuration_unless_a_flag_names_it():
    assert settings_from([]).harness is None, "no flag: [harness] jit decides"
    assert settings_from(["--harness"]).harness is True
    assert settings_from(["--no-harness"]).harness is False


async def test_a_server_with_no_harness_flag_does_not_override_the_configuration(tmp_path: Path, monkeypatch):
    """The SDK takes a missing keyword as "what the configuration says"; a keyword it is given as a value."""
    import zettcode.sdk

    seen: list[dict[str, object]] = []

    class Recorder:
        def __init__(self, workspace: object, **kwargs: object) -> None:
            seen.append(kwargs)

    monkeypatch.setattr(zettcode.sdk, "Client", Recorder)
    monkeypatch.setattr(zettcode.sdk, "list_models", lambda path: [types.SimpleNamespace(name="gpt", model="gpt")])
    from zettcode.server.runner import Runner

    runner = Runner(settings_from(["-w", str(tmp_path)]))
    await runner._open_client(model=None, effort=None, permission="deny", harness=None)
    await runner._open_client(model=None, effort=None, permission="deny", harness=False)
    await runner._open_client(model=None, effort=None, permission="deny", harness=True)

    assert "jit_harness" not in seen[0], "nothing was named, so nothing is forced"
    assert seen[1]["jit_harness"] is False and seen[2]["jit_harness"] is True
