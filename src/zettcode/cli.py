"""Command-line entry point for the ZettCode TUI.

Almost everything is configured in ``~/.zettcode/config.toml`` (see
:mod:`zettcode.config`), not on the command line: ``-w``/``--workspace`` picks
the directory to work in, ``-v``/``--version`` prints the version, ``-r``/``--resume`` picks the stored session to open
instead of a fresh one, and ``$ZETTCODE_CONFIG`` can point at a different
config file. ``zettcode update`` installs the newest release and exits.

Nothing beyond the standard library is imported at module level: ``zettcode
--help`` prints and exits, and paying for the agent runtime, the widget
library, or the theme loader before the user has asked for a session would make
the one command that needs none of them the slowest.
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .paths import resume_command

if TYPE_CHECKING:
    from .app.agent.agent import ZettCodeAgent
    from .app.ui.app import ZettCodeApp
    from .config import ZettCodeConfig
    from .tui import Theme, TuiApp


@dataclass(frozen=True, slots=True)
class Options:
    """What the command line asked for.

    Attributes:
        workspace: Directory the agent works in; the current one by default.
        resume: Stored session to open instead of a fresh one, if named.
        auto: Start with the shell permission at ``auto``, so no command asks.
        dry_run: Run the startup and exit instead of taking the terminal.
        command: The subcommand named (``"update"``), or ``None`` to start a session.
    """

    workspace: Path
    resume: str | None = None
    auto: bool = False
    dry_run: bool = False
    command: str | None = None


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
    parser = argparse.ArgumentParser(
        prog="zettcode",
        description="Run the ZettCode terminal coding agent",
    )
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
        "--auto",
        "--yolo",
        dest="auto",
        action="store_true",
        help="run shell commands without asking for the rest of this run",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="run the startup, paint one frame, and exit quietly (for profiling)",
    )
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")
    commands.add_parser(
        "update",
        help="install the newest release and exit",
        description="Install the newest release of ZettCode with the package manager it was installed with.",
    )
    resume = commands.add_parser(
        "resume",
        help="open a stored session by id (same as --resume)",
        description="Open a stored session instead of starting a new one; the same as `zettcode --resume SESSION`.",
    )
    resume.add_argument("session", metavar="SESSION", help="the session's id, as printed when it ended")
    args = parser.parse_args(argv)
    return Options(
        workspace=args.workspace, resume=args.resume, auto=args.auto, dry_run=args.dry_run, command=args.command
    )


def workspace_from_args(argv: list[str] | None = None) -> Path:
    """Return the workspace the arguments name, defaulting to the current directory."""
    return parse_args(argv).workspace


def session_exists(config: ZettCodeConfig, session_id: str) -> bool:
    """Return whether the store holds a session with this id in this workspace."""
    from .app.agent.storage import SessionStore

    return SessionStore(config.store, config.workspace).exists(session_id)


def resume_hint(agent: ZettCodeAgent) -> str | None:
    """Return the command that reopens this session, or None if there is nothing to reopen.

    A session the reader never sent anything to was never stored, so naming its
    id would hand them a command that fails. The line is only worth printing
    when the store has something to open.
    """
    if not session_exists(agent.runtime.config, agent.session_id):
        return None
    return resume_command(agent.session_id, agent.workspace)


def report_resume(agent: ZettCodeAgent) -> None:
    """Print one line naming the way back into the session that just ended."""
    hint = resume_hint(agent)
    if hint is not None:
        print(f"\nresume this session: {hint}\n")


def resolve_config(argv: list[str] | None = None) -> ZettCodeConfig:
    """Build the settings from the config file, reporting a bad file as a clean exit.

    The workspace is parsed first: ``--help`` exits inside ``argparse``, and it
    would be absurd for the flag that explains the program to load the agent
    runtime on the way out.
    """
    workspace = parse_args(argv).workspace
    from .config import load_config
    from .tui.capabilities import detect_reduced_motion

    try:
        return load_config(workspace, reduced_motion_default=detect_reduced_motion())
    except ValueError as error:
        raise SystemExit(f"zettcode: {error}") from error


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
        auto: Start with the shell permission at ``auto``, so no command asks.
        dry_run: Run the startup and exit without taking the terminal and
            without printing anything, so a profiler's output stands alone.
    """
    from .app import ZettCodeApp
    from .app.agent.agent import ZettCodeAgent
    from .tui import DARK, ThemeFileError, load_theme

    if resume is not None and not session_exists(config, resume):
        raise SystemExit(f"zettcode: no session {resume} in {config.store}")
    try:
        theme = load_theme(config.theme_file) if config.theme_file is not None else DARK
    except ThemeFileError as error:
        raise SystemExit(f"zettcode: {error}") from error
    agent = ZettCodeAgent.preview(config)
    if auto:
        agent.runtime.approve_all_shell_commands()
    app = ZettCodeApp(agent, theme=theme, auto_theme=config.theme_file is None)
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
    from .app.agent.agent import ZettCodeAgent
    from .tui import DARK, ThemeFileError, load_theme

    config = resolve_config()
    if options.resume is not None and not session_exists(config, options.resume):
        raise SystemExit(f"zettcode: no session {options.resume} in {config.store}")
    try:
        theme = load_theme(config.theme_file) if config.theme_file is not None else DARK
    except ThemeFileError as error:
        raise SystemExit(f"zettcode: {error}") from error
    agent = ZettCodeAgent.preview(config)
    if options.auto:
        # The rung the prompt's `a` and `/permission auto` both reach, taken before
        # the shell exists: nothing is announced, because there is no conversation
        # to announce it in and the status line already reads `· auto`.
        agent.runtime.approve_all_shell_commands()
    app = ZettCodeApp(agent, theme=theme, auto_theme=config.theme_file is None)
    if options.resume is not None:
        window = None
        if terminal is not None:

            def window() -> tuple[int, Theme]:
                # A palette the reader configured is the one the tree will paint in; with
                # none, the terminal chooses and the running app already has its answer.
                return terminal.width, theme if config.theme_file is not None else terminal.theme

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
        TuiApp(boot_tree(...))
        runner.run()
          enter alternate screen
          mount(), paint()          -----> the reader sees the composer
          query_background()   ......      its answer returns as input, not a wait
          start the reader
                                           resolve_config()
                                           import ZettCodeApp
                                           ZettCodeAgent.preview()
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
    from .paths import DEFAULT_LOG, config_path
    from .tui import DARK, Terminal, TerminalRunner, TuiApp

    # The header's right side is a file read rather than a settings load: the
    # frame that carries it is painted before any of this program's modules are
    # imported, and a reader who has just started the shell should see which
    # model and effort are about to answer, not an empty corner that fills in a
    # tenth of a second later. A file that cannot be read leaves it empty and
    # the application fills it in on the swap.
    tui = TuiApp(
        boot_tree(
            Path(options.workspace).expanduser().resolve(),
            resuming=options.resume is not None,
            model=labels.model_name(config_path()),
        ),
        theme=DARK,
        auto_theme=True,
    )
    runner = TerminalRunner(tui, terminal=Terminal(diagnostics=DEFAULT_LOG))
    running = asyncio.ensure_future(runner.run())
    app: ZettCodeApp | None = None
    try:
        app = await asyncio.to_thread(build_application, options, terminal=tui)
        app.adopt(tui)
        # The imports the first turn needs start once the real frame is on the screen,
        # not when the tree is swapped in: they share the interpreter's one lock with
        # the drawing, and the frame is what the reader is waiting for.
        runner.after_next_paint(app.start_background)
        await running
    finally:
        if app is not None:
            await app.stop_background()
        tui.exit()
        await asyncio.gather(running, return_exceptions=True)
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
    options = parse_args()
    if options.command == "update":
        from .update import update_program

        raise SystemExit(update_program())
    tune_collector()
    _name_process()
    try:
        if options.dry_run:
            asyncio.run(async_main(resolve_config(), resume=options.resume, auto=options.auto, dry_run=True))
            return
        asyncio.run(launch(options))
    finally:
        freeze_heap()


if __name__ == "__main__":
    main()
