"""Command-line entry point for the ZettCode TUI.

Almost everything is configured in ``~/.zettcode/config.toml`` (see
:mod:`zettcode.config`), not on the command line: ``-w``/``--workspace`` picks
the directory to work in, ``-r``/``--resume`` picks the stored session to open
instead of a fresh one, and ``$ZETTCODE_CONFIG`` can point at a different
config file.

Nothing beyond the standard library is imported at module level: ``zettcode
--help`` prints and exits, and paying for the agent runtime, the widget
library, or the theme loader before the user has asked for a session would make
the one command that needs none of them the slowest.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .app.agent.agent import ZettCodeAgent
    from .app.ui.app import ZettCodeApp
    from .config import ZettCodeConfig


@dataclass(frozen=True, slots=True)
class Options:
    """What the command line asked for.

    Attributes:
        workspace: Directory the agent works in; the current one by default.
        resume: Stored session to open instead of a fresh one, if named.
        dry_run: Run the startup and exit instead of taking the terminal.
    """

    workspace: Path
    resume: str | None = None
    dry_run: bool = False


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
        "--dry-run",
        action="store_true",
        help="run the startup, paint one frame, and exit quietly (for profiling)",
    )
    args = parser.parse_args(argv)
    return Options(workspace=args.workspace, resume=args.resume, dry_run=args.dry_run)


def workspace_from_args(argv: list[str] | None = None) -> Path:
    """Return the workspace the arguments name, defaulting to the current directory."""
    return parse_args(argv).workspace


def resume_command(session_id: str, workspace: Path) -> str:
    """Return the command that reopens one stored session from anywhere."""
    return f"zettcode --resume {shlex.quote(session_id)} --workspace {shlex.quote(str(workspace))}"


def session_exists(config: ZettCodeConfig, session_id: str) -> bool:
    """Return whether the store holds a session with this id in this workspace."""
    from .app.agent.storage import SessionStore

    return SessionStore(config.store, config.workspace).read(session_id).header is not None


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


async def async_main(config: ZettCodeConfig, *, resume: str | None = None, dry_run: bool = False) -> None:
    """Own runtime lifecycle around the full-screen application.

    The runtime is built by the first turn, not here: ``preview`` has
    everything the shell paints with, and the provider SDK is imported while
    the reader is looking at the first frame.

    Args:
        config: Settings loaded from the config file.
        resume: Stored session to open instead of a fresh one; an id the store
            does not hold is reported before the terminal is taken over.
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


def build_application(options: Options) -> ZettCodeApp:
    """Read the settings and build the application, off the event loop.

    Runs in a worker thread: the config read, the shell's imports, and the
    runtime preview together cost about 130 ms, and the composer is already on
    screen taking the reader's keys while this happens.
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
    app = ZettCodeApp(agent, theme=theme, auto_theme=config.theme_file is None)
    if options.resume is not None:
        app.restore_session(options.resume)
    return app


async def launch(options: Options) -> None:
    """Put the composer on screen, then build the application behind it.

    Nothing the first frame shows needs the config, the runtime, or the widget
    library, so the terminal is taken with a frame drawn from the framework
    alone, the application is built in a worker thread, and the running app is
    handed the real tree as soon as it exists.

    Two lanes run at once and meet at the swap. The times are this machine's
    medians from ``python -m perf.startup``; the order is what the tests pin —
    the frame before the terminal is asked anything, and nothing on it that the
    shell does not draw in the same cell.

    .. code-block:: text

        main thread: the frame             worker thread: the application
        ------------------------------     ------------------------------------
        import the boot frame   ~50 ms
        TuiApp(boot_tree(...))
        runner.run()
          enter alternate screen
          mount(), paint()      ~65 ms --> the reader sees the composer
          query_background()    ......    its answer returns as input, not a wait
          start the reader
                                           resolve_config()           ~60 ms
                                           import ZettCodeApp         ~57 ms
                                           ZettCodeAgent.preview()     ~2 ms
                                           ZettCodeApp(agent, ...)
                                           restore_session()   (--resume only)
        app.adopt(tui)         <--------- the build returns
        tui.set_root(...)     ~160 ms --> the real tree replaces it, whole frame
                                           start_background(): warm the runtime,
                                           check for a release

    Args:
        options: What the command line asked for.
    """
    from .app.ui.boot import boot_tree
    from .paths import DEFAULT_LOG
    from .tui import DARK, Terminal, TerminalRunner, TuiApp

    tui = TuiApp(
        boot_tree(Path(options.workspace).expanduser().resolve(), resuming=options.resume is not None),
        theme=DARK,
        auto_theme=True,
    )
    runner = TerminalRunner(tui, terminal=Terminal(diagnostics=DEFAULT_LOG))
    running = asyncio.ensure_future(runner.run())
    app: ZettCodeApp | None = None
    try:
        app = await asyncio.to_thread(build_application, options)
        app.adopt(tui)
        app.start_background()
        await running
    finally:
        if app is not None:
            await app.stop_background()
        tui.exit()
        await asyncio.gather(running, return_exceptions=True)
    report_resume(app.agent)


def main() -> None:
    """Installed console-script entry point."""
    options = parse_args()
    _name_process()
    if options.dry_run:
        asyncio.run(async_main(resolve_config(), resume=options.resume, dry_run=True))
        return
    asyncio.run(launch(options))


if __name__ == "__main__":
    main()
