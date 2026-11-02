"""Command-line entry point for the ZettCode TUI.

Almost everything is configured in ``~/.zettcode/config.toml`` (see
:mod:`zettcode.config`), not on the command line: ``-w``/``--workspace`` picks
the directory to work in, ``-v``/``--version`` prints the version, ``-r``/``--resume`` (or the ``resume`` subcommand) picks the stored session to open
instead of a fresh one, and ``$ZETTCODE_CONFIG`` can point at a different
config file. ``zettcode update`` (or ``upgrade``) installs the newest release and exits, and ``zettcode doctor``
asks every configured model a one-line question and reports which of them answer. ``zettcode prompt`` sends one prompt
without opening the terminal and prints the answer (see :mod:`zettcode.oneshot`). ``zettcode daemon``, ``zettcode
broker``, ``zettcode gateway`` and ``zettcode plugin`` are their own commands, parsed apart from a session start.

Nothing beyond the standard library is imported at module level: ``zettcode
--help`` prints and exits, and paying for the agent runtime, the widget
library, or the theme loader before the user has asked for a session would make
the one command that needs none of them the slowest.
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from . import logging_setup
from .paths import resume_command

logger = logging.getLogger("zettcode.terminal")

if TYPE_CHECKING:
    from collections.abc import Callable

    #: What ``add_subparsers`` returns, which the standard library gives no public name to.
    Subcommands = argparse._SubParsersAction[argparse.ArgumentParser]

    from .app.agent.agent import TerminalAgent
    from .app.ui.app import ZettCodeApp
    from .config import ZettCodeConfig
    from .tui import Theme, TuiApp


@dataclass(frozen=True, slots=True)
class Options:
    """What the command line asked for.

    Attributes:
        workspace: Directory the agent works in; the current one by default.
        resume: Stored session to open instead of a fresh one, if named.
        auto: Start with the shell permission at ``full`` (``--full``, or its old name ``--auto``), so no command
            asks and none is sandboxed.
        dry_run: Run the startup and exit instead of taking the terminal.
        command: The subcommand named (``"update"`` for ``update`` and ``upgrade`` alike, ``"doctor"`` or ``"prompt"``),
            or ``None`` to start a session.
        prompt: For ``prompt``, the text to send; ``None`` reads it from standard input.
        model: For ``prompt``, the model to use by the name ``/model`` lists, instead of the first one.
        effort: For ``prompt``, the reasoning level, instead of the config file's.
        continue_request: For ``prompt``, pick up the request that was cut short instead of sending ``prompt``.
    """

    workspace: Path
    resume: str | None = None
    auto: bool = False
    dry_run: bool = False
    command: str | None = None
    prompt: str | None = None
    model: str | None = None
    effort: str | None = None
    continue_request: bool = False


def version_text() -> str:
    """Return the line ``--version`` prints: this program, and what it runs on.

    The agent library is named because it is the half of the program that is released
    separately, so a report that says only "0.1.5" leaves out the version most likely to
    matter. It is looked up here, when asked for, rather than at import: ``--help`` and every
    start would otherwise pay for a metadata scan to print nothing.
    """
    import platform
    from importlib import metadata

    from . import __version__

    try:
        agent = metadata.version("zett-agent")
    except metadata.PackageNotFoundError:  # pragma: no cover - a source tree without its dependencies
        agent = "not installed"
    return f"zettcode {__version__} (zett-agent {agent}, Python {platform.python_version()})"


class _Version(argparse.Action):
    """Print :func:`version_text` and exit, the way ``action="version"`` does but computed on demand."""

    def __call__(self, parser, namespace, values, option_string=None) -> None:
        print(version_text())
        parser.exit()


def parse_args(argv: list[str] | None = None) -> Options:
    """Return the workspace to run in and the session to resume, if any.

    Args:
        argv: Arguments to parse; ``None`` reads the process's own.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    # `upgrade` is another name for `update`; nothing after this point needs to know it was used.
    command = "update" if args.command == "upgrade" else args.command
    return _OPTIONS.get(command, _plain_options)(parser, args, command)


def _build_parser() -> argparse.ArgumentParser:
    """Return the parser: the options every start takes, and one subparser for each subcommand."""
    parser = argparse.ArgumentParser(
        prog="zettcode",
        description="Run the ZettCode terminal coding agent",
    )
    _add_global_options(parser)
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")
    _add_update(commands)
    _add_doctor(commands)
    _add_resume(commands)
    _add_prompt(commands)
    _add_daemon(commands)
    _add_broker(commands)
    _add_gateway(commands)
    _add_plugin(commands)
    return parser


def _add_global_options(parser: argparse.ArgumentParser) -> None:
    """Add the options that apply to starting a session, and that ``-w`` and ``--auto`` of a subcommand mean as well."""
    parser.add_argument(
        "-v",
        "-V",
        "--version",
        action=_Version,
        nargs=0,
        help="print the version and exit",
    )
    parser.add_argument(
        "-w",
        "--workspace",
        metavar="DIR",
        type=Path,
        default=Path.cwd(),
        help="directory to work in (default: the current directory)",
    )
    parser.add_argument(
        "-r",
        "--resume",
        metavar="SESSION",
        default=None,
        help="open a stored session by id instead of starting a new one",
    )
    parser.add_argument(
        "--full",
        "--auto",
        "--yolo",
        dest="auto",
        action="store_true",
        help="run shell commands with full access and without asking, for the rest of this run",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="run the startup, paint one frame, and exit quietly (for profiling)",
    )


def _add_update(commands: Subcommands) -> None:
    """Add ``update``, and ``upgrade`` as another name for it."""
    commands.add_parser(
        "update",
        aliases=["upgrade"],
        help="install the newest release and exit (also: upgrade)",
        description="Install the newest release of ZettCode with the package manager it was installed with.",
    )


def _add_doctor(commands: Subcommands) -> None:
    """Add ``doctor``."""
    commands.add_parser(
        "doctor",
        help="check that each configured model answers, and exit",
        description="Ask every model in the config file one short question and report which of them answer.",
    )


def _add_resume(commands: Subcommands) -> None:
    """Add ``resume SESSION``."""
    resume = commands.add_parser(
        "resume",
        help="open a stored session by id (same as --resume)",
        description="Open a stored session instead of starting a new one; the same as `zettcode --resume SESSION`.",
    )
    resume.add_argument("session", metavar="SESSION", help="the session's id, as printed when it ended")
    # Written after the word, the way the line the shell prints on exit reads: `zettcode resume ID -w DIR`. The
    # default is suppressed so it does not overwrite the directory the top-level `-w` already chose.
    resume.add_argument(
        "-w",
        "--workspace",
        metavar="DIR",
        type=Path,
        default=argparse.SUPPRESS,
        help="directory the session belongs to (default: the current directory)",
    )


def _add_daemon(commands: Subcommands) -> None:
    """Add ``daemon``: background agents another session can message.

    Only the name is declared here, so that ``zettcode --help`` lists it. Its subcommands, and the work they do, are
    parsed and run by :mod:`zettcode.daemon.cli`, which the entry point reaches without importing the rest of this
    module's command line: a terminal start pays nothing for a command it is not running.
    """
    commands.add_parser(
        "daemon",
        help="run and manage background agents: daemon list | spawn | kill",
        description="Start a background agent another session reaches with send_message, and manage the ones running.",
    )


def _add_broker(commands: Subcommands) -> None:
    """Add ``broker``: the session broker's start, stop and restart.

    Only the name is declared here, so that ``zettcode --help`` lists it; its action is parsed and run by
    :mod:`zettcode.broker.cli`, which a terminal start never imports.
    """
    commands.add_parser(
        "broker",
        help="start, stop or restart the session broker: broker start | stop | restart | reload",
        description=(
            "Start, stop or restart the background broker that lets sessions on this machine message each other. "
            "After an upgrade a broker that speaks an older protocol is replaced by itself when zettcode starts."
        ),
    )


def _add_gateway(commands: Subcommands) -> None:
    """Add ``gateway``: the web page for the daemons, served until stopped.

    Only the name is declared here, so that ``zettcode --help`` lists it. Its flags are the gateway's own
    (``--host``, ``--port``, ``--token`` and the rest), parsed by :mod:`zettcode.gateway.cli`.
    """
    commands.add_parser(
        "gateway",
        help="serve the page for background agents: gateway start | stop | restart",
        description=(
            "A web page for the background agents on this machine: list the daemons and the sessions that are "
            "running, start and stop daemons, and talk to any of them. With no action it serves in this terminal; "
            "`start`, `stop` and `restart` manage one in the background. `zettcode gateway --help` has the flags."
        ),
    )


#: The name ``--help`` lists for the plugin command, and every word it answers to: ``plugins`` is the name it had
#: before, kept for the scripts that already run it, and deliberately not advertised.
PLUGIN_COMMAND = "plugin"
PLUGIN_COMMANDS = (PLUGIN_COMMAND, "plugins")


def _add_plugin(commands: Subcommands) -> None:
    """Add ``plugin``: listing, installing, removing and switching plugins in this environment.

    Only the name is declared here, so that ``zettcode --help`` lists it; the actions are parsed and run by
    :mod:`zettcode.plugin_cli`, which is never imported by a session start.
    """
    commands.add_parser(
        PLUGIN_COMMAND,
        help="list, install, remove or switch a plugin: plugin list | install | uninstall | enable | disable",
        description=(
            "Install a plugin into the Python environment ZettCode runs in (or copy a single .py file into "
            "~/.zettcode/plugins), remove one, or enable/disable one for the next start. Start ZettCode again "
            "afterwards."
        ),
    )


def _add_prompt(commands: Subcommands) -> None:
    """Add ``prompt``: one prompt, no terminal."""
    ask = commands.add_parser(
        "prompt",
        help="send one prompt without opening the terminal, and print the answer",
        description=(
            "Send one prompt, print the answer on stdout, and exit. Uses the first model and a new session\n"
            "unless -m and -s say otherwise. Everything but the answer goes to stderr; shell commands\n"
            "run without asking.\n\n"
            "Exit status: 0 answered, 1 failed or stopped early, 2 bad arguments, 3 nothing to continue."
        ),
        epilog=(
            "examples:\n"
            "  zettcode prompt 'explain this repo'\n"
            "  git diff | zettcode prompt 'review this change'\n"
            "  zettcode prompt --continue -s 01a10b75"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ask.add_argument(
        "text",
        nargs="?",
        metavar="PROMPT",
        help="what to ask; omit it, or give -, to read it from standard input",
    )
    ask.add_argument(
        "-c",
        "--continue",
        dest="continue_request",
        action="store_true",
        help="pick up the request that was cut short, as /continue does (takes no prompt; needs -s)",
    )
    ask.add_argument(
        "-m",
        "--model",
        metavar="NAME",
        help="model to use, by the name /model lists (default: the first one)",
    )
    ask.add_argument(
        "-s",
        "--session",
        metavar="SESSION",
        help="stored session to continue (default: a new one)",
    )
    ask.add_argument("-e", "--effort", metavar="LEVEL", help="the reasoning level (default: the config file's)")
    # Also accepted after the word, where it is natural to type it; unset here so it does not undo the one before it.
    ask.add_argument(
        "-w", "--workspace", metavar="DIR", type=Path, default=argparse.SUPPRESS, help="directory to work in"
    )


def _plain_options(parser: argparse.ArgumentParser, args: argparse.Namespace, command: str | None) -> Options:
    """Return the options of a start with no subcommand, and of the subcommands that take none of their own."""
    return Options(workspace=args.workspace, resume=args.resume, auto=args.auto, dry_run=args.dry_run, command=command)


def _resume_options(parser: argparse.ArgumentParser, args: argparse.Namespace, command: str | None) -> Options:
    """Return the options of ``resume SESSION``, which is ``--resume SESSION`` spelled as a word."""
    # Opening a session is a way of starting one, not a different program, so it is the option's twin.
    if args.resume is not None and args.resume != args.session:
        parser.error(f"--resume {args.resume} and resume {args.session} name different sessions")
    return Options(workspace=args.workspace, resume=args.session, auto=args.auto, dry_run=args.dry_run)


def _prompt_options(parser: argparse.ArgumentParser, args: argparse.Namespace, command: str | None) -> Options:
    """Return the options of ``prompt``, refusing what cannot be meant: two sessions, or a prompt to continue with."""
    if args.session is not None and args.resume is not None and args.session != args.resume:
        parser.error(f"--resume {args.resume} and --session {args.session} name different sessions")
    if args.continue_request and args.text is not None:
        parser.error("--continue takes no prompt: it picks up the request that was cut short")
    if args.continue_request and args.session is None and args.resume is None:
        parser.error("--continue needs --session: name the session whose request was cut short")
    return Options(
        workspace=args.workspace,
        resume=args.session if args.session is not None else args.resume,
        command=command,
        prompt=args.text,
        model=args.model,
        effort=args.effort,
        continue_request=args.continue_request,
    )


#: How the arguments of a subcommand become :class:`Options`; a command that is not here takes :func:`_plain_options`.
_OPTIONS: dict[str, Callable[[argparse.ArgumentParser, argparse.Namespace, str | None], Options]] = {
    "resume": _resume_options,
    "prompt": _prompt_options,
}


def workspace_from_args(argv: list[str] | None = None) -> Path:
    """Return the workspace the arguments name, defaulting to the current directory."""
    return parse_args(argv).workspace


def session_exists(config: ZettCodeConfig, session_id: str) -> bool:
    """Return whether the store holds a session with this id in this workspace."""
    from .engine.storage import SessionStore

    return SessionStore(config.store, config.workspace).exists(session_id)


def resume_hint(agent: TerminalAgent) -> str | None:
    """Return the command that reopens this session, or None if there is nothing to reopen.

    A session the reader never sent anything to was never stored, so naming its
    id would hand them a command that fails. The line is only worth printing
    when the store has something to open.
    """
    if not session_exists(agent.runtime.config, agent.session_id):
        return None
    return resume_command(agent.session_id, agent.workspace)


def report_resume(agent: TerminalAgent) -> None:
    """Print one line naming the way back into the session that just ended."""
    hint = resume_hint(agent)
    if hint is not None:
        print(f"\nresume this session: {hint}\n")


def resolve_config(argv: list[str] | None = None, *, require_models: bool = True) -> ZettCodeConfig:
    """Build the settings from the config file, reporting a bad file as a clean exit.

    The workspace is parsed first: ``--help`` exits inside ``argparse``, and it
    would be absurd for the flag that explains the program to load the agent
    runtime on the way out.

    Args:
        argv: Arguments to read the workspace from; ``sys.argv`` by default.
        require_models: Refuse a file that lists no models. The terminal passes ``False``: a machine that has
            never been set up reaches the shell and its ``/config``, and only a request insists on a model.
    """
    workspace = parse_args(argv).workspace
    from .config import load_config
    from .tui.capabilities import detect_reduced_motion

    try:
        return load_config(workspace, reduced_motion_default=detect_reduced_motion(), require_models=require_models)
    except ValueError as error:
        raise SystemExit(f"zettcode: {error}") from error


def chosen_theme(agent: TerminalAgent) -> Theme | None:
    """Return the palette the reader chose, or ``None`` when the terminal's own light or dark should pick.

    A palette is a choice when ``[ui] theme`` names one, or ``~/.zettcode/theme.toml`` exists; the file is laid
    over the named palette, so it can adjust a few colours of it. The name is looked up where ``/theme`` looks:
    the plugins' palettes (the built-in ones among them), then the reader's own files. A name nobody has, or a
    file that cannot be read, is reported as a clean exit rather than a traceback, and the session the agent has
    already begun is let go of first so it leaves nothing behind.
    """
    from .tui import ThemeFileError, load_theme

    config = agent.runtime.config
    try:
        named = agent.themes.load(config.theme) if config.theme else None
        if config.theme_file is not None:
            return load_theme(config.theme_file, base=named)
    except ThemeFileError as error:
        agent.runtime.session_locks.release()
        raise SystemExit(f"zettcode: {error}") from error
    return named


def boot_theme() -> Theme | None:
    """Return the palette the configured start paints, read without building the application.

    The frame that goes up before the application exists should already be in the reader's palette: a start that
    opens in a light palette would otherwise paint a dark frame, then swap it a tenth of a second later. Only the
    two things that decide the palette are read here - ``[ui] theme`` in the config file and a theme file of the
    reader's - because a plugin's palette cannot be known before the plugins load. A name only a plugin has, an
    unreadable file, and any other mistake are left to the real application, which knows the plugins and reports
    the error; the boot frame is not the place for either.

    Returns:
        The chosen palette, or ``None`` when the terminal's own light or dark should pick.
    """
    from ._compat import tomllib
    from .paths import DEFAULT_THEME_FILE, DEFAULT_THEMES_DIR, config_path
    from .tui import ThemeCatalog, ThemeFileError, bundled_themes, load_theme

    path = config_path()
    if not path.is_file():
        # Only a file can be read for a palette: a FIFO would block the frame this is read for, and a path that
        # exists and is not a file is refused before the terminal is taken.
        return None
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        return None
    ui = data.get("ui")
    requested = ui.get("theme") if isinstance(ui, dict) else None
    try:
        named = ThemeCatalog(bundled_themes(), DEFAULT_THEMES_DIR).load(requested) if requested else None
        if DEFAULT_THEME_FILE.is_file():
            return load_theme(DEFAULT_THEME_FILE, base=named)
    except ThemeFileError:
        return None
    return named


async def async_main(
    config: ZettCodeConfig, *, resume: str | None = None, auto: bool = False, dry_run: bool = False
) -> None:
    """Own runtime lifecycle around the full-screen application.

    The runtime is built by the first turn, not here: ``preview`` has
    everything the shell paints with, and the provider SDK is imported while
    the reader is looking at the first frame.

    Args:
        config: Settings loaded from the config file.
        resume: Stored session to open instead of a fresh one; an id the store
            does not hold is reported before the terminal is taken over.
        auto: Start with the shell permission at ``full``, so no command asks and none is sandboxed.
        dry_run: Run the startup and exit without taking the terminal and
            without printing anything, so a profiler's output stands alone.
    """
    from .app import ZettCodeApp
    from .app.agent.agent import TerminalAgent
    from .tui import DARK

    if resume is not None and not session_exists(config, resume):
        raise SystemExit(f"zettcode: no session {resume} in {config.store}")
    agent = TerminalAgent.preview(config)
    chosen = chosen_theme(agent)
    theme = chosen if chosen is not None else DARK
    if auto:
        agent.runtime.approve_all_shell_commands()
    app = ZettCodeApp(agent, theme=theme, auto_theme=chosen is None)
    if resume is not None:
        app.restore_session(resume)
    if dry_run:
        # Nothing is printed: a profiler's own output is the report, and a line
        # of ours would only mix into it.
        try:
            await app.dry_run()
        finally:
            await agent.aclose()
        return
    try:
        await app.run()
    finally:
        await agent.aclose()
        report_resume(agent)


def _name_process() -> None:
    """Name the foreground process, independently of the terminal's OSC title.

    iTerm2's job label and VS Code's default tab template inspect the process
    name, so changing the window title alone leaves them saying ``python3``.
    Import the native helper only after parsing flags; help never needs it.
    Windows cannot rename an executable this way and uses the OSC title instead.
    Failure to name a process must not prevent the application from starting.
    """
    if os.name != "posix":
        return
    try:
        from setproctitle import setproctitle

        setproctitle("zettcode")
    except (ImportError, OSError, RuntimeError):
        return


def build_application(options: Options, *, terminal: TuiApp | None = None) -> ZettCodeApp:
    """Read the settings and build the application, off the event loop.

    Runs in a worker thread: the config read, the shell's imports, and the
    runtime preview together cost about 130 ms, and the composer is already on
    screen taking the reader's keys while this happens.

    Args:
        options: What the command line asked for.
        terminal: The app already painting the boot frame, when there is one. A
            resumed session's rows are measured while the file is read, and they
            can only be measured at the width and in the palette of the terminal
            they are going to: this app knows both, and the tree built here does
            not yet.
    """
    from .app import ZettCodeApp
    from .app.agent.agent import TerminalAgent
    from .tui import DARK

    config = resolve_config(require_models=False)
    if options.resume is not None and not session_exists(config, options.resume):
        raise SystemExit(f"zettcode: no session {options.resume} in {config.store}")
    agent = TerminalAgent.preview(config)
    chosen = chosen_theme(agent)
    theme = chosen if chosen is not None else DARK
    if options.auto:
        # The rung the prompt's `a` and `/permission full` both reach, taken before
        # the shell exists: nothing is announced, because there is no conversation
        # to announce it in and the status line already reads `· full`.
        agent.runtime.approve_all_shell_commands()
    app = ZettCodeApp(agent, theme=theme, auto_theme=chosen is None)
    if options.resume is not None:
        window = None
        if terminal is not None:

            def window() -> tuple[int, Theme]:
                # A palette the reader configured is the one the tree will paint in; with
                # none, the terminal chooses and the running app already has its answer.
                return terminal.width, chosen if chosen is not None else terminal.theme

        app.restore_session(options.resume, window=window)
    return app


async def launch(options: Options) -> None:
    """Put the composer on screen, then build the application behind it.

    Nothing the first frame shows needs the config, the runtime, or the widget
    library, so the terminal is taken with a frame drawn from the framework
    alone, the application is built in a worker thread, and the running app is
    handed the real tree as soon as it exists. The work that belongs to the first
    turn — the provider and its client, the token counter, the release check —
    starts once the frame carrying the real tree has been written: it shares the
    interpreter's one lock with the drawing, and the frame is what the reader is
    waiting for.

    Two lanes run at once and meet at the swap; the order is what the tests pin —
    the frame before the terminal is asked anything, and nothing on it that the
    shell does not draw in the same cell.

    .. code-block:: text

        main thread: the frame             worker thread: the application
        ------------------------------     ------------------------------------
        import the boot frame
        TuiApp(boot_tree(...), theme=the palette the config names)
        runner.run()
          enter alternate screen
          mount(), paint()          -----> the reader sees the composer
          query_background()   ......      its answer returns as input, not a wait
          start the reader
                                           resolve_config()
                                           import ZettCodeApp
                                           TerminalAgent.preview()
                                           ZettCodeApp(agent, ...)
                                           restore_session()   (--resume only)
        app.adopt(tui)         <---------  the build returns
        tui.set_root(...)          ----->  the real tree replaces it, whole frame
                                           start_background(): warm the runtime,
                                           check for a release

    When each moment arrives, in milliseconds from the process starting, on this
    machine at 120 columns. The right column is a 25 MB session of 5714
    messages; the left is the same launch with nothing to restore.

    +--------------------------------------+---------+---------+
    | moment                               | fresh   | resume  |
    +======================================+=========+=========+
    | the interpreter, and the cli imported|    67   |    66   |
    | the build thread starts              |    86   |    84   |
    | the boot frame is on screen          |    88   |    86   |
    | the shell and the agent are imported |   200   |   203   |
    | the stored file is parsed            |     -   |   293   |
    | it is replayed into the rows         |     -   |   339   |
    | those rows are measured              |   203   |   400   |
    | the tree is swapped in, content on   |   206   |   405   |
    | the background imports are done      |   747   |  1009   |
    +--------------------------------------+---------+---------+

    Medians of five runs. The resume half is what ``python -m perf.resume``
    measures again on any machine; the shape is what matters here. A character
    cell is 20 ms, and a blank stretch on the main lane is the frame loop waiting
    for the build rather than working:

    .. code-block:: text

        resume — the 25 MB session, at 120 columns
                        ms
                        |    |    |    |    |    |    |    |    |    |
                        0    100  200  300  400  500  600  700  800  900
          main          ###==               =
          worker            ######pppprrmmmm
          hidden            ..............................................
                                            ^

          # interpreter + imports   = a frame   p parsing the file
          r replaying it into rows   m measuring those rows   . warming the runtime
          ^ the reader can type; everything to its right in "hidden" is behind them

        fresh start — the same launch with nothing to restore
                        ms
                        |    |    |    |    |    |    |    |    |    |
                        0    100  200  300  400  500  600  700  800  900
          main          ###==     =
          worker            ######
          hidden            ..................................
                                  ^

          # interpreter + imports   = a frame   . warming the runtime
          ^ the reader can type

    The warm-up is the part the reader never waits for: on the resumed launch it
    runs for another 600 ms after they can type, and the first turn waits for it
    there rather than here.

    Args:
        options: What the command line asked for.
    """
    from .app.ui import labels
    from .app.ui.boot import boot_tree
    from .paths import DEFAULT_LOG, check_config_path, config_path
    from .tui import DARK, Terminal, TerminalRunner, TuiApp

    # `check_config_path` comes from `paths` and not from the settings module: this runs before the first frame,
    # and importing `zettcode.config` here costs it 40-70 ms — two character cells of the numbers measured below.
    # Before the terminal is taken, and before anything reads that path for the frame: a config path that exists
    # and is not a file is a sentence on a plain terminal, not a frame that exits from the build thread behind it
    # (or blocks on a FIFO while the palette is read).
    try:
        check_config_path()
    except ValueError as error:
        raise SystemExit(f"zettcode: {error}") from error

    # The header's right side is a file read rather than a settings load, and so is the palette: this frame is
    # painted before any of this program's modules are imported, and a reader should see which model will answer,
    # and the colours they chose, on the first frame. A file that cannot be read leaves a row empty or a palette
    # unset, and the application corrects either on the swap. A palette only a plugin offers cannot be named this
    # early, so that one still arrives with the application.
    picked = boot_theme()
    tui = TuiApp(
        boot_tree(
            Path(options.workspace).expanduser().resolve(),
            resuming=options.resume is not None,
            model=labels.model_name(config_path()),
            hidden=labels.hidden_parts(config_path()),
        ),
        theme=picked or DARK,
        auto_theme=picked is None,
    )
    runner = TerminalRunner(tui, terminal=Terminal(diagnostics=DEFAULT_LOG))
    running = asyncio.ensure_future(runner.run())
    app: ZettCodeApp | None = None

    def session_id() -> str | None:
        client = getattr(app, "client", None)
        return None if client is None else client.session.id

    logging_setup.setup("terminal")
    logging_setup.rotate_text(DEFAULT_LOG)
    logger.info(
        "cli.start",
        extra={
            "workspace": str(Path(options.workspace).expanduser().resolve()),
            "resume": options.resume is not None,
        },
    )
    try:
        app = await asyncio.to_thread(build_application, options, terminal=tui)
        app.adopt(tui)
        logger.info("app.ready", extra={"session": session_id()})
        # The imports the first turn needs start once the real frame is on the screen,
        # not when the tree is swapped in: they share the interpreter's one lock with
        # the drawing, and the frame is what the reader is waiting for.
        runner.after_next_paint(app.start_background)
        await running
    except BaseException as error:
        if not isinstance(error, (asyncio.CancelledError, SystemExit, KeyboardInterrupt)):
            logger.exception("cli.failed", extra={"session": session_id()})
        raise
    finally:
        if app is not None:
            await app.stop_background()
        tui.exit()
        await asyncio.gather(running, return_exceptions=True)
        logger.info("cli.stop", extra={"session": session_id()})
    report_resume(app.agent)


def freeze_heap() -> None:
    """Free the heap so the interpreter's last collection does not walk it.

    A process that imported the model SDKs spends 150-300 ms dying — measured on
    a bare ``import openai, anthropic``, so it is nothing this program does — and
    almost all of it is the cyclic collector's final pass over everything those
    libraries allocated. Moving the live heap into the permanent generation
    takes it out of that pass: the same exit takes 5 ms, and it is still a
    normal one, since ``gc`` is asked to skip work rather than the process told
    to skip its shutdown. Nothing after a shell has left allocates anything that
    wants collecting.
    """
    gc.freeze()


#: Allocations the collector waits for before it looks at the newest objects. The default (2000) is
#: sized for scripts; this program keeps a live heap of a few hundred thousand objects — the model
#: SDKs, the widget tree, the rows of a long transcript — and a frame allocates thousands, so the
#: default had the collector interrupting a scroll every few frames. Measured with the same scroll
#: over a ten-thousand-line transcript: frames past one frame's budget 13 in 4200 with the default,
#: 4 in 4200 with this. Anything it leaves is still collected, just less often. That makes a
#: collection rare; :mod:`zettcode.app.ui.gc_policy` decides *when* one may happen (only while work
#: is in flight, never while the reader types) and freezes the SDK heap so it is cheap when it does.
GC_YOUNG_THRESHOLD = 100_000


def tune_collector() -> None:
    """Make the cyclic collector interrupt the interface less often; the older generations are untouched."""
    _, older, oldest = gc.get_threshold()
    gc.set_threshold(GC_YOUNG_THRESHOLD, older, oldest)


def main() -> None:
    """Installed console-script entry point."""
    argv = sys.argv[1:]
    if argv[:1] != ["broker"]:
        # After an upgrade the broker still running may speak the old protocol. A glance at its note and lock is all
        # this costs, and a process of its own replaces it only when it is older: the start never waits for it.
        from .broker.reload import check_in_background

        check_in_background()
    if argv[:1] == ["daemon"]:
        # Parsed by its own command: `daemon` takes subcommands of its own, which this parser would flatten into the
        # options a terminal start takes.
        from .daemon.cli import daemon_program

        raise SystemExit(daemon_program(argv[1:]))
    if argv[:1] == ["broker"]:
        # The same: `broker start` and `broker stop` are words of their own, not flags of a session start.
        from .broker.cli import broker_program
        from .daemon.companions import DaemonCompanions

        # The broker knows nothing of daemons; a restart is given them so it can ask before it strands them.
        raise SystemExit(broker_program(argv[1:], DaemonCompanions()))
    if argv[:1] == ["gateway"]:
        # Its flags (`--host`, `--port`, the token) are the gateway's, parsed by the command that serves it.
        from .gateway.cli import main as gateway_main

        gateway_main(argv[1:])
        return
    if argv and argv[0] in PLUGIN_COMMANDS:
        # The actions over the plugins, parsed by the command that installs and switches them. `plugins` is the
        # name this command had before; it is not listed in --help, and it still works for the scripts that use it.
        from .plugin_cli import plugin_program

        raise SystemExit(plugin_program(argv[1:]))
    options = parse_args()
    if options.command == "update":
        from .update import update_program

        raise SystemExit(update_program())
    if options.command == "doctor":
        from .doctor import doctor_program

        raise SystemExit(doctor_program(resolve_config()))
    if options.command == "prompt":
        from .oneshot import prompt_program

        raise SystemExit(prompt_program(options))
    if options.command == PLUGIN_COMMAND:
        # Only reached when another option came before the word (`zettcode -w DIR plugin`), which the dispatch above
        # does not see because it reads the first word alone. Its own parser prints the usage and asks for an action
        # rather than opening a session nobody asked for.
        from .plugin_cli import plugin_program

        raise SystemExit(plugin_program([]))
    tune_collector()
    _name_process()
    try:
        if options.dry_run:
            asyncio.run(
                async_main(resolve_config(require_models=False), resume=options.resume, auto=options.auto, dry_run=True)
            )
            return
        asyncio.run(launch(options))
    finally:
        freeze_heap()


if __name__ == "__main__":
    main()
