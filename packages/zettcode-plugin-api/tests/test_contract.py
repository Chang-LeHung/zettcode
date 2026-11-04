"""The plugin contract is the bottom of the graph it defines, and says only what it can keep.

Three things hold the design up, and each is checked where it can be broken: the facade names exactly what it
resolves, importing a contract module pulls nothing of the program in with it, and the registry the presenters are
registered into obeys the priority rule the guide promises.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path
from typing import ClassVar

import pytest

import zettcode.plugin_api as api
from zettcode.plugin_api.entries import EntryKind, TextEntry
from zettcode.plugin_api.presenters import Presenter, Presenters
from zettcode.tui import DARK, Span, Style, TextLine


def test_the_facade_publishes_what_it_maps_and_every_name_resolves():
    assert sorted(api._EXPORTS) == sorted(api.__all__)
    for name in api.__all__:
        assert getattr(api, name) is not None, name


def test_an_unknown_name_is_an_attribute_error_and_not_a_silent_none():
    with pytest.raises(AttributeError, match="no attribute 'Nothing'"):
        api.Nothing  # noqa: B018


#: The one module that needs the agent framework by its nature: `TuiPlugin` subclasses the engine's `Plugin`, whose
#: hooks are the framework's. Every other module is about rows, commands and widgets and must not drag the runtime in.
NEEDS_THE_AGENT_FRAMEWORK = {"plugin"}

#: What the boot frame must not have loaded: it is drawn before any of these exist.
HEAVY = (
    "zett_agent",
    "pydantic",
    "httpx",
    "zettcode.config",
    "zettcode.engine.core",
    "zettcode.app",
    "zettcode.presenters",
)


def _contract_modules() -> list[str]:
    files = sorted(Path(api.__file__).parent.glob("*.py"))
    return [file.stem for file in files if file.stem != "__init__"]


@pytest.mark.parametrize("module", [name for name in _contract_modules() if name not in NEEDS_THE_AGENT_FRAMEWORK])
def test_importing_a_contract_module_pulls_nothing_of_the_program_in(module: str):
    """The boot frame is drawn before the settings, the runtime or a provider SDK exist, and it imports these.

    Every module is checked, so a new one is held to this without anyone adding it to a list; the one that is the
    agent side of the contract is named above, with the reason.
    """
    script = (
        f"import sys, zettcode.plugin_api.{module}\n"
        f"heavy = {HEAVY!r}\n"
        "print(sorted(name for name in sys.modules if name.split('.')[0] in heavy or any(name.startswith(h) for h in heavy)))\n"
    )

    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True)

    assert result.stdout.strip() == "[]", result.stdout


def test_the_modules_that_need_the_agent_framework_are_the_ones_named_and_no_more():
    """Guards the exception list: it can only shrink, because a module that stops needing the framework should say so."""
    needs = []
    for module in _contract_modules():
        script = f"import sys, zettcode.plugin_api.{module}; print('zett_agent' in sys.modules)"
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True)
        if result.stdout.strip() == "True":
            needs.append(module)
    assert set(needs) == NEEDS_THE_AGENT_FRAMEWORK, needs


def test_the_contract_names_no_implementation_of_itself():
    """The built-in rows, the shell and the loader are written against these modules, never the other way round."""
    files = sorted(Path(api.__file__).parent.glob("*.py"))
    assert len(files) > 8, files
    for file in files:
        body = file.read_text(encoding="utf-8")
        for implementation in ("zettcode.app", "zettcode.presenters"):
            assert f"from {implementation}" not in body and f"import {implementation}" not in body, (
                file.name,
                implementation,
            )


class _Notice(Presenter[TextEntry]):
    kind: ClassVar[EntryKind] = EntryKind.NOTICE

    def __init__(self, label: str, priority: int = 0) -> None:
        self.label = label
        self.priority = priority  # type: ignore[misc]

    def lines(self, entry: TextEntry, width: int, theme, frame: int) -> list[TextLine]:
        return [TextLine((Span(self.label, Style()),))]


def _entry() -> TextEntry:
    return TextEntry(id=1, kind=EntryKind.NOTICE, text="hello")


def test_the_stronger_claim_on_a_row_wins_and_an_equal_one_goes_to_the_later():
    first, second, strong = _Notice("first"), _Notice("second"), _Notice("strong", priority=5)

    assert Presenters([first, second]).for_entry(_entry()) is second
    assert Presenters([strong, first, second]).for_entry(_entry()) is strong


def test_replacing_appends_so_a_plugin_that_registers_last_draws_the_row():
    registry = Presenters([_Notice("built in")])
    mine = _Notice("mine")

    assert registry.replacing(mine).for_entry(_entry()) is mine
    assert registry.replacing(mine).lines(_entry(), 20, DARK, 0)[0].spans[0].text == "mine"


#: What evaluates an annotation, which turns a name that only exists for the type checker into a failure at run time.
#: This is the set of tools this repository uses, not every tool that could: a library that introspects annotations in
#: its own way (`attrs.resolve_types`, `typeguard`, `beartype`) is a new name, added here with its first use.
EVALUATES_ANNOTATIONS = {"get_type_hints", "TypeAdapter", "BaseModel", "create_model", "ConfigDict"}


def test_nothing_in_the_contract_evaluates_an_annotation():
    """The `types` extra is safe only because no annotation here is ever evaluated.

    The contract names the SDK's `Client`, `ModelInfo` and `Usage` in annotations and imports them for the type checker
    alone, so a plugin that does not install the extra still imports every name. That holds while the annotations stay
    strings: the day a contract class is a pydantic model, or something calls `typing.get_type_hints` on one, a name that
    exists only under `TYPE_CHECKING` is a `NameError` for the plugin author. (Today `get_type_hints` already fails on
    nine of these classes, for `Path` and `Theme` as much as for the SDK — which is the same fact seen from the other
    side, and why the guard is on the cause and not on that call succeeding.)

    This reads the contract's own modules. The accident that is likelier is in a *consumer* -- a `TypeAdapter` over a
    contract class in the server, a page resolving hints on one -- and that is
    `packages/zettcode/tests/test_structure.py::test_no_annotation_of_the_plugin_contract_is_evaluated_anywhere`, which
    scans every distribution and allows only the engine's own types to be evaluated.
    """
    offenders: list[str] = []
    for file in sorted(Path(api.__file__).parent.glob("*.py")):
        tree = ast.parse(file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: set[str] = set()
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, ast.keyword) and node.arg == "eval_str":
                names.add("eval_str")
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                names.update(alias.name.split(".")[-1] for alias in node.names)
                if isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] == "pydantic":
                    names.add("pydantic")
            for name in names & (EVALUATES_ANNOTATIONS | {"eval_str", "pydantic"}):
                offenders.append(f"{file.name}:{node.lineno} uses {name}")

    assert offenders == []
