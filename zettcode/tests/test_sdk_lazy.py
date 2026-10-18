"""Importing the SDK costs nothing, and only what is used is loaded.

The check runs in a fresh interpreter, because the test process has long since imported the agent.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

HEAVY = ("zett_agent", "openai", "anthropic", "zettcode.tui", "zettcode.config", "zettcode.app")


def loaded_after(code: str) -> dict[str, bool]:
    """Run ``code`` in a clean interpreter and report which heavy packages were imported by the end."""
    script = (
        "import sys\n"
        + code
        + "\nprint({name: any(m == name or m.startswith(name + '.') for m in sys.modules) for name in "
        + repr(HEAVY)
        + "})\n"
    )
    done = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True)
    return eval(done.stdout.strip().splitlines()[-1])  # noqa: S307 - our own output


@pytest.mark.parametrize(
    "module",
    [
        "zettcode.sdk",
        "zettcode.sdk.errors",
        "zettcode.sdk.types",
        "zettcode.sdk.events",
        "zettcode.sdk.handlers",
        "zettcode.sdk.session",
        "zettcode.sdk.client",
    ],
)
def test_importing_a_module_of_the_sdk_loads_neither_the_agent_nor_the_application(module):
    assert not any(loaded_after(f"import {module}").values())


def test_naming_the_public_classes_loads_them_and_still_not_the_agent():
    names = loaded_after(
        "import zettcode.sdk as zc\n"
        "zc.Client, zc.Session, zc.RunStream, zc.prompt, zc.prompt_sync, zc.RunResult, zc.Usage, zc.Image\n"
        "zc.TextDelta, zc.ApprovalRequested, zc.approve_all, zc.ZettCodeError"
    )

    assert not any(names.values())


def test_making_a_client_is_what_loads_the_agent(tmp_path):
    code = (
        "import tempfile, zettcode.sdk as zc\n"
        f"zc.Client({str(tmp_path)!r}, models=[{{'model': 'm', 'token': 't'}}], store={str(tmp_path / 's')!r})"
    )

    names = loaded_after(code)

    assert names["zett_agent"] and names["zettcode.app"] and names["zettcode.config"]


def test_the_listed_names_are_exactly_the_ones_that_resolve():
    import zettcode.sdk as zc

    assert sorted(zc.__all__) == sorted(zc._EXPORTS)
    assert len(set(zc.__all__)) == len(zc.__all__)
    for name in zc.__all__:
        assert getattr(zc, name) is not None, name


def test_only_what_is_needed_is_exported_at_the_top():
    import zettcode.sdk as zc

    for rare in ("Steered", "Notice", "ModelStopped", "UsageUpdated", "RawEvent", "AnyEvent", "ModelInfo", "Message"):
        assert rare not in zc.__all__
        with pytest.raises(AttributeError, match=rare):
            getattr(zc, rare)


def test_the_rarer_names_are_in_the_submodules():
    from zettcode.sdk.errors import RunTimeoutError, SessionBusyError
    from zettcode.sdk.events import AnyEvent, Notice, RawEvent, Steered
    from zettcode.sdk.types import ContextReport, Message, ModelInfo, SessionInfo

    assert all((RunTimeoutError, SessionBusyError, AnyEvent, Notice, RawEvent, Steered))
    assert all((ContextReport, Message, ModelInfo, SessionInfo))


def test_an_unknown_name_is_an_attribute_error_that_names_it():
    import zettcode.sdk as zc

    with pytest.raises(AttributeError, match="no attribute 'nope'"):
        zc.nope  # noqa: B018


def test_a_resolved_name_is_kept_so_the_lookup_happens_once():
    import zettcode.sdk as zc

    first = zc.Usage

    assert vars(zc)["Usage"] is first and zc.Usage is first


def test_dir_lists_the_public_names_without_loading_them():
    names = loaded_after("import zettcode.sdk as zc\nassert 'Client' in dir(zc) and 'prompt' in dir(zc)")

    assert not any(names.values())


def test_a_star_import_brings_in_the_public_names():
    namespace: dict[str, object] = {}
    exec("from zettcode.sdk import *", namespace)  # noqa: S102

    import zettcode.sdk as zc

    assert {name for name in namespace if not name.startswith("__")} == set(zc.__all__)


def test_the_package_ships_its_type_marker():
    from pathlib import Path

    import zettcode

    assert (Path(zettcode.__file__).parent / "py.typed").is_file()
