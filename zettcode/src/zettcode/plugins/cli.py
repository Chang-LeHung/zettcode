"""``zettcode plugins``: install, remove, enable and disable plugins in the environment ZettCode runs in.

A plugin is either a Python distribution that publishes a class under ``zettcode.plugins``, or a single ``.py`` file
in :attr:`ZettCodeConfig.plugins_dir` (``~/.zettcode/plugins`` by default); installing it is the opt-in (see
:mod:`zettcode.engine.plugins.loader`). This command is the shell side of that:

* ``install`` hands a local path or a GitHub repository to the installer the running environment has (pip, or uv when
  a uv tool install has no pip). A single ``.py`` file is copied into the plugins folder instead — it is not a
  distribution, and nothing needs to be installed for it to load.
* ``uninstall`` removes a file, or the distribution behind a name.
* ``enable`` and ``disable`` write the plugin switch file, which is what the next start reads.

It decides nothing about loading: a plugin installed here is picked up at the next start, and one removed or
disabled is gone then. The command exists so a reader does not have to know which Python owns the environment,
whether it has pip, or where the switch file is.
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from zettcode.engine.plugins.switches import SwitchState

EXIT_OK = 0
EXIT_FAILED = 1

#: A GitHub repository in its short form: ``owner/repo``, then an optional ``@ref`` or ``#fragment``.
_GITHUB_SHORT = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:[@#].*)?$")

#: Schemes pip installs straight from, and which this passes through untouched.
_VCS = ("git+", "hg+", "svn+", "bzr+")


@dataclass(frozen=True, slots=True)
class Installer:
    """The program that installs into this interpreter, and which one it is for the few flags that differ."""

    kind: str
    command: tuple[str, ...]


def build_parser() -> argparse.ArgumentParser:
    """Return the parser for ``zettcode plugins`` and its four actions."""
    parser = argparse.ArgumentParser(
        prog="zettcode plugins",
        description=(
            "Install a plugin into the environment ZettCode runs in, remove one, or switch one for the next start. "
            "A plugin is a Python distribution, or a single .py file in ~/.zettcode/plugins, that adds commands, "
            "tools or screen rows. Start ZettCode again after a change."
        ),
    )
    commands = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)

    install_parser = commands.add_parser(
        "install",
        help="install a plugin from a local path, a single file or a GitHub repository",
        description=(
            "Install a plugin from a local directory or archive, a single .py file, or a GitHub repository. The "
            "target is handed to pip (or uv, when this environment has no pip) for the running interpreter, so it "
            "lands where ZettCode will load it; a single file is copied into ~/.zettcode/plugins."
        ),
        epilog=(
            "examples:\n"
            "  zettcode plugins install ./greeter\n"
            "  zettcode plugins install ./greeter.py\n"
            "  zettcode plugins install owner/repo\n"
            "  zettcode plugins install owner/repo@v1.2.0\n"
            "  zettcode plugins install https://github.com/owner/repo/tree/main/plugins/greeter\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    install_parser.add_argument(
        "target",
        help="a local path (a project directory, a wheel, an sdist or a single .py file), or a GitHub repository: "
        "owner/repo, gh:owner/repo, or its https URL, with an optional @ref",
    )

    uninstall_parser = commands.add_parser(
        "uninstall",
        help="remove an installed plugin or a single-file plugin",
        description=(
            "Remove a single-file plugin from ~/.zettcode/plugins, or the distribution that carries a plugin. The "
            "name is the file's stem, the distribution's own, or the entry-point name /plugins shows."
        ),
    )
    uninstall_parser.add_argument(
        "name", help="the file's stem, the distribution name, or the plugin's entry-point name"
    )

    for action, wording in (
        ("enable", "load it at the next start"),
        ("disable", "leave it out at the next start"),
    ):
        switch = commands.add_parser(
            action,
            help=f"{action} a plugin for the next start",
            description=(
                f"Write the plugin switch so the next start will {wording}. Installed distributions and single-file "
                "plugins are switched here; a plugin compiled into the program is switched by its own setting in the "
                "configuration file (the /plugins panel does that)."
            ),
        )
        switch.add_argument("name", help="the plugin's origin: its distribution, entry-point name, or file stem")
    return parser


def plugins_program(argv: list[str] | None = None) -> int:
    """Entry point of ``zettcode plugins``; 0 done, 1 failed, 2 for bad arguments."""
    args = build_parser().parse_args(argv)
    if args.command == "install":
        return install(args.target)
    if args.command == "uninstall":
        return uninstall(args.name)
    return switch(args.name, enabled=args.command == "enable")


def install(target: str) -> int:
    """Install ``target`` -- a single file is copied, anything else is handed to pip -- and say what is next."""
    path = Path(target).expanduser()
    if path.is_file() and path.suffix.lower() == ".py":
        return _install_file(path)
    try:
        requirement = requirement_for(target)
    except ValueError as error:
        print(f"zettcode plugins: {error}", file=sys.stderr)
        return EXIT_FAILED
    tool = installer()
    if tool is None:
        print(NO_INSTALLER, file=sys.stderr)
        return EXIT_FAILED
    print(f"installing {requirement}")
    code = run([*action(tool, "install"), "--upgrade", requirement])
    if code != EXIT_OK:
        print("zettcode plugins: the install failed; the output above says why", file=sys.stderr)
        return EXIT_FAILED
    print("installed; start ZettCode again for it to load")
    return EXIT_OK


def _install_file(source: Path) -> int:
    """Copy a single-file plugin into the plugins folder, after checking it defines a plugin class."""
    try:
        plugin_classes(source)
    except ValueError as error:
        print(f"zettcode plugins: {error}", file=sys.stderr)
        return EXIT_FAILED
    module = module_name(source.stem)
    target = plugins_dir() / f"{module}.py"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.tmp")
        temporary.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        os.replace(temporary, target)
    except OSError as error:
        print(f"zettcode plugins: {target} could not be written: {error}", file=sys.stderr)
        return EXIT_FAILED
    print(f"installed {target}; start ZettCode again to load {module}")
    return EXIT_OK


def uninstall(name: str) -> int:
    """Remove a single-file plugin, or the distribution behind ``name``."""
    name = name.strip()
    path = plugins_dir() / f"{module_name(name)}.py"
    if path.is_file():
        try:
            path.unlink()
        except OSError as error:
            print(f"zettcode plugins: {path} could not be removed: {error}", file=sys.stderr)
            return EXIT_FAILED
        print(f"removed {path}; start ZettCode again to drop what it added")
        return EXIT_OK
    distribution = distribution_for(name)
    if distribution is None:
        print(
            f"zettcode plugins: no installed distribution or plugin file is called {name!r}; /plugins lists each "
            "plugin's origin",
            file=sys.stderr,
        )
        return EXIT_FAILED
    tool = installer()
    if tool is None:
        print(NO_INSTALLER, file=sys.stderr)
        return EXIT_FAILED
    print(f"uninstalling {distribution}")
    # pip asks before removing; uv does not and has no such flag.
    flags = ["-y", distribution] if tool.kind == "pip" else [distribution]
    code = run([*action(tool, "uninstall"), *flags])
    if code != EXIT_OK:
        print("zettcode plugins: the uninstall failed; the output above says why", file=sys.stderr)
        return EXIT_FAILED
    print("uninstalled; start ZettCode again to drop what it added")
    return EXIT_OK


def plugin_state() -> SwitchState:
    """Read what a switch needs from the configuration file, without requiring a model to be configured.

    The command may run on a machine that has not been set up yet, so it reads the ``[plugins]`` table itself rather
    than building the whole settings object, whose validation insists on a model.

    Raises:
        ValueError: The file cannot be read, is not TOML, or its ``[plugins]`` table is malformed.
    """
    from zettcode._compat import tomllib
    from zettcode.paths import DEFAULT_PLUGINS_FILE, config_path

    path = config_path()
    data: dict[str, object] = {}
    try:
        if path.is_file():
            data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"{path}: {error}") from error
    plugins = data.get("plugins", {})
    if not isinstance(plugins, dict):
        raise ValueError(f"{path}: [plugins] must be a table")
    enabled = plugins.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError(f"{path}: plugins.enabled must be true or false")
    disable = plugins.get("disable", [])
    if not isinstance(disable, list) or any(not isinstance(name, str) or not name.strip() for name in disable):
        raise ValueError(f"{path}: plugins.disable must be an array of non-empty strings")
    return SwitchState(
        plugins_file=DEFAULT_PLUGINS_FILE,
        plugins_enabled=enabled,
        disabled_plugins=tuple(name.strip() for name in disable),
    )


def switch(name: str, *, enabled: bool) -> int:
    """Write ``name`` on or off in the plugin switch file, for the next start."""
    name = name.strip()
    try:
        config = plugin_state()
    except (OSError, ValueError) as error:
        print(f"zettcode plugins: the configuration could not be read: {error}", file=sys.stderr)
        return EXIT_FAILED
    if not _known(config, name):
        print(
            f"zettcode plugins: no installed plugin or plugin file is called {name!r}; /plugins lists the ones there "
            "are (a compiled-in plugin is switched by its own setting, in that list)",
            file=sys.stderr,
        )
        return EXIT_FAILED
    from zettcode.engine.plugins.switches import set_installed

    try:
        set_installed(config, name, enabled=enabled)
    except ValueError as error:
        print(f"zettcode plugins: {error}", file=sys.stderr)
        return EXIT_FAILED
    print(f"{'enabled' if enabled else 'disabled'} {name} for the next start")
    return EXIT_OK


def _known(config: object, name: str) -> bool:
    """Return whether ``name`` is something the switch file can hold: a file here, an entry point, or a recorded name."""
    from importlib.metadata import entry_points

    from zettcode.config import read_disabled_plugins
    from zettcode.engine.plugins.loader import PLUGIN_ENTRY_POINT_GROUP

    if (plugins_dir() / f"{module_name(name)}.py").is_file():
        return True
    if any(point.name == name for point in entry_points(group=PLUGIN_ENTRY_POINT_GROUP)):
        return True
    plugins_file = getattr(config, "plugins_file", None)
    return isinstance(plugins_file, Path) and name in read_disabled_plugins(plugins_file)


#: What a failure to find pip or uv says. A uv tool environment has no pip, but its uv does.
NO_INSTALLER = (
    "zettcode plugins: neither pip nor uv can install into this environment; install the plugin with the tool that "
    "owns it (for a uv tool install: `uv tool install --force --with <target> zettcode`)"
)


def requirement_for(target: str) -> str:
    """Return what pip is given for a target: a local path made absolute, or a GitHub repository as a git URL.

    Raises:
        ValueError: The target is neither an existing path nor a GitHub repository this command understands.
    """
    text = target.strip()
    if not text:
        raise ValueError("a plugin is a local path or a GitHub repository")
    path = Path(text).expanduser()
    if path.exists():
        return str(path.resolve())
    if text.startswith(_VCS):
        return text
    if text.startswith(("gh:", "github:", "https://github.com/", "http://github.com/")):
        return _github(text)
    if _GITHUB_SHORT.match(text):
        return _github(text)
    raise ValueError(f"not a local path or a GitHub repository: {target}")


def _github(text: str) -> str:
    """Turn any of the accepted GitHub spellings into the ``git+https://...`` pip takes."""
    if text.startswith("gh:"):
        text = text[len("gh:") :]
    elif text.startswith("github:"):
        text = text[len("github:") :]
    elif "github.com/" in text:
        text = text.split("github.com/", 1)[1]
    fragment = ""
    if "#" in text:
        text, rest = text.split("#", 1)
        fragment = "#" + rest
    ref = ""
    if "/tree/" in text:
        text, rest = text.split("/tree/", 1)
        ref, _, subtree = rest.partition("/")
        if subtree and not fragment:
            fragment = "#subdirectory=" + quote(subtree.strip("/"))
    if "@" in text:
        text, ref = text.rsplit("@", 1)
    repo = text.strip("/")
    if repo.endswith(".git"):
        repo = repo[:-4]
    if repo.count("/") != 1 or not all(repo.split("/")):
        raise ValueError(f"not a GitHub owner/repository: {text}")
    url = f"git+https://github.com/{repo}.git"
    if ref:
        url += f"@{ref}"
    return url + fragment


def plugin_classes(path: Path) -> list[str]:
    """Return the classes a standalone file defines that derive from a name ending in ``Plugin``.

    It reads the file, it does not import it: installing must not run a plugin's code. A file with no such class is
    refused here, before it is copied into a folder the next start would try to load it from.

    Raises:
        ValueError: The file cannot be read, is not valid Python, or defines no plugin class.
    """
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError(f"{path} could not be read: {error}") from error
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as error:
        raise ValueError(f"{path} is not valid Python: {error.msg} (line {error.lineno})") from error
    found = [
        node.name
        for node in tree.body
        if isinstance(node, ast.ClassDef) and (node.name == "Plugin" or _derives_from_plugin(node))
    ]
    if not found:
        raise ValueError(f"{path} defines no class deriving from Plugin or TuiPlugin")
    return found


def _derives_from_plugin(node: ast.ClassDef) -> bool:
    """Return whether a class lists a base whose final name is ``Plugin`` (``Plugin``, ``TuiPlugin``, ``pkg.Plugin``)."""
    for base in node.bases:
        name = base.attr if isinstance(base, ast.Attribute) else base.id if isinstance(base, ast.Name) else None
        if name is not None and name.endswith("Plugin"):
            return True
    return False


def module_name(stem: str) -> str:
    """Return the module name a file's stem installs under: identifier characters, never a leading digit."""
    name = re.sub(r"\W", "_", stem, flags=re.ASCII) or "plugin"
    return f"plugin_{name}" if name[0].isdigit() else name


def plugins_dir() -> Path:
    """Return the folder single-file plugins live in, as the loader will read it."""
    from zettcode.paths import plugins_dir as folder

    return folder()


def distribution_for(name: str) -> str | None:
    """Return the installed distribution's name for a distribution or plugin entry-point name, if there is one."""
    from importlib import metadata

    from zettcode.engine.plugins.loader import PLUGIN_ENTRY_POINT_GROUP

    try:
        found = metadata.distribution(name)
    except metadata.PackageNotFoundError:
        found = None
    if found is not None:
        return found.metadata["Name"] or found.name
    for candidate in metadata.distributions():
        for point in candidate.entry_points:
            if point.group == PLUGIN_ENTRY_POINT_GROUP and point.name == name:
                return candidate.metadata["Name"] or candidate.name
    return None


def installer() -> Installer | None:
    """Return the command that installs into this interpreter: pip when it has one, else uv's pip."""
    if _pip_works():
        return Installer("pip", (sys.executable, "-m", "pip"))
    uv = shutil.which("uv")
    if uv is not None:
        return Installer("uv", (uv, "pip"))
    return None


def action(tool: Installer, name: str) -> list[str]:
    """Return the start of ``tool``'s install or uninstall command, with this interpreter named for uv.

    ``uv pip`` takes ``--python`` after the action (``uv pip install --python ...``), not before it; pip installs into
    the interpreter it is run with.
    """
    if tool.kind == "uv":
        return [*tool.command, name, "--python", sys.executable]
    return [*tool.command, name]


def _pip_works() -> bool:
    """Return whether this interpreter has pip: a uv tool environment does not."""
    try:
        done = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "pip", "--version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return False
    return done.returncode == 0


def run(command: Sequence[str]) -> int:
    """Run one installer command, its output going to the terminal, and return its exit status.

    Args:
        command: The program and its arguments, already built for this environment.
    """
    try:
        return subprocess.run(command, check=False).returncode  # noqa: S603
    except OSError as error:
        print(f"zettcode plugins: could not run {command[0]}: {error}", file=sys.stderr)
        return 127


__all__ = [
    "Installer",
    "NO_INSTALLER",
    "action",
    "build_parser",
    "distribution_for",
    "install",
    "installer",
    "module_name",
    "plugin_classes",
    "plugin_state",
    "plugins_dir",
    "plugins_program",
    "requirement_for",
    "run",
    "switch",
    "uninstall",
]
