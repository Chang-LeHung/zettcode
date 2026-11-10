"""``zettcode-weixin``: log in by scanning, then leave a background process to answer the chat.

The command is a handover. ``zettcode-weixin`` starts a login, draws the QR code in the terminal, waits for the
phone, writes the handshake away, and starts a process that owns the connection from then on. It then prints
where that process is and exits, because a QR code and a running agent do not belong in the same window: the
reader scans and closes the terminal, and the agent keeps answering.

Running it again is how a login is replaced. A code is only good for the login it started, so the old process is
stopped first and a new one takes over — the same daemon and the same conversation, a new connection to WeChat.

A message may carry pictures: they travel with the text to the daemon, which puts them in the same prompt. The
answer is text, because the platform's send takes text — an agent that writes a file says where it wrote it.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import signal
import sys
from pathlib import Path

from zettcode.version import __version__

from . import qr
from .worker import Worker, command

#: Where the login, the cursor and the lock live when ``--state-dir`` is not given.
DEFAULT_DIR = Path.home() / ".zettcode" / "im" / "weixin"

#: Seconds to wait for the phone to scan, and seconds between looks at the login.
LOGIN_TIMEOUT = 300.0
POLL = 2.0


def build_parser() -> argparse.ArgumentParser:
    """Return the parser: the four things a bridge does, and the settings they share."""
    parser = argparse.ArgumentParser(
        prog="zettcode-weixin",
        description=(
            "Drive one ZettCode daemon from a personal WeChat conversation. With no command it logs in: a QR "
            "code to scan, then a background process that answers the chat, pictures included."
        ),
    )
    parser.add_argument("--version", action="version", version=f"zettcode-weixin {__version__}")
    commands = parser.add_subparsers(dest="command")
    for name, help_line in (
        ("login", "scan a QR code and start the background process (the default)"),
        ("start", "start the background process with the stored login, without scanning"),
        ("set", "change the settings the daemon is started with, and apply them now"),
        ("run", "run the bridge in this terminal (what the background process does)"),
        ("status", "say whether a bridge is running and what it is doing"),
        ("stop", "stop the background process"),
        ("logs", "print the end of the background process's log"),
    ):
        sub = commands.add_parser(name, help=help_line, description=help_line)
        _common(sub, login=name in ("login", "set"), run=name == "run")
        if name == "set":
            sub.add_argument(
                "--keep-daemon",
                action="store_true",
                help="leave a running daemon alone; by default it is stopped so the new settings take effect",
            )
        if name == "login":
            sub.add_argument(
                "--login-timeout",
                type=float,
                default=LOGIN_TIMEOUT,
                help=f"seconds to wait for the scan (default: {int(LOGIN_TIMEOUT)})",
            )
        if name == "logs":
            sub.add_argument("-n", "--lines", type=int, default=40, help="how many lines to print (default: 40)")
    return parser


def _common(sub: argparse.ArgumentParser, *, login: bool, run: bool) -> None:
    """Add the settings a login writes and a run reads."""
    sub.add_argument(
        "--state-dir", type=Path, default=DEFAULT_DIR, help=f"where the bridge keeps itself (default: {DEFAULT_DIR})"
    )
    if login:
        sub.add_argument(
            "-w",
            "--workspace",
            type=Path,
            default=None,
            help="directory the agent works in (default: the one already stored, or the current directory)",
        )
        sub.add_argument("--model", default=None, help="the model the daemon runs on (default: the one already stored)")
        sub.add_argument("--effort", default=None, help="the reasoning level (default: the one already stored)")
        sub.add_argument(
            "--permission",
            choices=("deny", "safe", "full"),
            default=None,
            help="the daemon's shell level (default: the one already stored, or full)",
        )
        sub.add_argument(
            "--allow",
            action="append",
            default=None,
            help="a sender id allowed to drive the agent, replacing the stored list; repeatable",
        )
        sub.add_argument(
            "--allow-all",
            action="store_true",
            default=None,
            help="let anyone who can message the bot drive the agent (it has a shell and this machine's files)",
        )
    if run:
        sub.add_argument(
            "--turn-timeout", type=float, default=600.0, help="seconds to wait for one answer (default: 600)"
        )


def main(argv: list[str] | None = None) -> int:
    """Parse the command line and do what it says; return the exit status."""
    arguments = build_parser().parse_args(argv)
    if arguments.command is None:
        # No command: the shared flags still apply, so parse them for the login the reader meant.
        arguments = build_parser().parse_args(["login", *(sys.argv[1:] if argv is None else argv)])
    state_dir: Path = arguments.state_dir.expanduser()
    if arguments.command == "login":
        return asyncio.run(_login(arguments, state_dir))
    if arguments.command == "start":
        return _start(state_dir)
    if arguments.command == "set":
        return _set(arguments, state_dir)
    if arguments.command == "run":
        return asyncio.run(_run(arguments, state_dir))
    if arguments.command == "status":
        return _status(state_dir)
    if arguments.command == "stop":
        print(Worker(state_dir).stop())
        return 0
    if arguments.command == "logs":
        text = Worker(state_dir).tail(arguments.lines)
        print(text or f"nothing has been written to {Worker(state_dir).log} yet")
        return 0
    raise AssertionError(f"unknown command {arguments.command!r}")


# -- login ---------------------------------------------------------------------------------------------
async def _login(arguments: argparse.Namespace, state_dir: Path) -> int:
    """Draw the QR code, wait for the scan, write the state, and start the background process."""
    from agim.models import LoginStatus  # type: ignore[import-untyped]
    from agim.wechat.client import WeChatClient  # type: ignore[import-untyped]

    from ..state import BridgeState

    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    worker = Worker(state_dir)
    # The running bridge stays up while the code is on screen: a scan that fails, or a reader who walks away,
    # must not cost the bridge they already had. Nothing is written until the login has finished, so the old
    # process keeps working on the state it started with.
    state = BridgeState.load(state_dir / "state.json")
    client = WeChatClient()
    state_now = None
    try:
        handshake = await client.login()
        print("Scan this with WeChat (the code is only good for this login):\n")
        print(qr.show(handshake.qr_content))
        if handshake.qr_url:
            print(f"or open {handshake.qr_url}\n")
        said: str = ""
        verify: str | None = None
        deadline = asyncio.get_running_loop().time() + max(1.0, arguments.login_timeout)
        while asyncio.get_running_loop().time() < deadline:
            state_now = await client.is_login(handshake, verify_code=verify)
            status = state_now.status
            if status == LoginStatus.CONNECTED:
                break
            if status in (LoginStatus.FAILED, LoginStatus.EXPIRED):
                print(f"\nthe login did not finish: {state_now.message}")
                return 2
            if status == LoginStatus.SCANNED and said != "scanned":
                said = "scanned"
                print("\nscanned \u2014 confirm the login on your phone")
            elif status == LoginStatus.VERIFY_REQUIRED and verify is None:
                print(f"\n{state_now.message}")
                verify = input("pairing code: ").strip() or None
            await asyncio.sleep(POLL)
        else:
            print(f"\nnothing was scanned in {int(arguments.login_timeout)} seconds; run the command again")
            return 2
    finally:
        await client.aclose()

    credentials = state_now.credentials if state_now is not None else None
    state.handshake = handshake.model_dump(mode="json")
    state.credentials = credentials.model_dump(mode="json") if credentials is not None else {}
    # A new login is a new connection: the cursor, the reply contexts and the answered ids belong to the old one —
    # the platform numbers messages from the start again, so an id kept across a login can name a new message.
    # The session stays, so the conversation and its history carry over.
    state.cursor = ""
    state.chats.clear()
    state.seen.clear()
    # A login renews the connection; the settings are what the reader decided and outlive it. A flag replaces its
    # setting, and a flag that was not given leaves the stored one alone — a re-scan that forgot `--allow` used to
    # wipe the allow-list and turn every message into a refusal.
    previous_workspace = state.workspace
    previous_session = state.session_id
    _apply_settings(state, arguments)
    if state.workspace != previous_workspace:
        # A session lives in one workspace: its id in another would resume a conversation that is not there.
        state.session_id = ""
    if not state.token():
        # A login without a token is a bridge that cannot send or receive, and a background process that says
        # nothing about it. Better to say so here, where the reader is still watching the phone.
        print("the login finished, but WeChat handed back no bot token. Nothing was started; run the command again")
        return 3

    # Only now is the old process stopped, and it is stopped before the new state is written: one that is still
    # running keeps its own copy and would write that back over the new token at its next message.
    if worker.running():
        print(worker.stop(), "\u2014 the new login replaces it")
        if worker.running():
            print("the old bridge did not stop, so the new login was not saved. Stop it by hand and run again.")
            return 3
    state.save()
    if previous_session and state.workspace != previous_workspace:
        # The daemon of the old workspace is nobody's now: the bridge will start a new one here, and leaving the old
        # one running is a session a reader never asked to keep. Best effort: a busy one is reported, not waited on.
        from zettcode.sdk.daemons import stop_daemon
        from zettcode.sdk.errors import SessionNotFoundError

        try:
            said = await stop_daemon(previous_session, keep=True)
        except SessionNotFoundError:
            said = "no daemon was running for the old workspace"
        except Exception as error:  # noqa: BLE001 - the login is finished either way
            said = f"the daemon of the old workspace was left running ({error})"
        print(f"daemon     {said}")
    elif previous_session and (arguments.model or arguments.effort or arguments.permission):
        print(
            "note       a daemon that is already running keeps the settings it was started with; "
            "`zettcode-weixin set` applies new ones now"
        )
    try:
        pid = worker.start(command("--state-dir", str(state_dir)))
    except RuntimeError as error:
        print(f"the login was saved, but the background process did not start: {error}")
        return 3
    print(f"\nlogged in. The bridge is running (pid {pid}) and will answer messages as they come.")
    print(f"  log:    {worker.log}")
    print(f"  stop:   zettcode-weixin stop --state-dir {state_dir}")
    if not state.allow and not state.allow_all:
        print("  note:   no sender is allowed yet \u2014 each message is refused and names the id to allow")
    elif state.allow_all:
        print("  allows: anyone who can message the bot")
    else:
        print(f"  allows: {', '.join(state.allow)}")
    return 0


# -- run -----------------------------------------------------------------------------------------------
async def _run(arguments: argparse.Namespace, state_dir: Path) -> int:
    """Run the bridge here, which is what the background process does."""
    from agim.models import LoginHandshake, LoginStatus
    from agim.wechat.client import WeChatClient

    from zettcode.filelock import SingletonLock

    from ..bridge import Bridge, BridgeSettings
    from ..guard import DaemonGuard
    from ..link import SessionLink
    from ..state import BridgeState

    state = BridgeState.load(state_dir / "state.json")
    if not state.logged_in:
        print(f"no login in {state_dir}: run `zettcode-weixin` first")
        return 2
    client = WeChatClient(token=state.token())
    link = SessionLink(
        session_id=_bridge_id(state_dir),
        handle="weixin",
        workspace=state.workspace,
        timeout=arguments.turn_timeout,
    )
    lock: SingletonLock | None = None
    try:
        # The stored handshake is the *login* handshake, and it expires once the code has been scanned — the token
        # it produced lives on. So this is a hint, not a gate: the poll below is what proves the token works.
        try:
            handshake = LoginHandshake.model_validate(state.handshake)
            login = await client.is_login(handshake)
        except Exception as error:  # noqa: BLE001 - a handshake this build cannot read says nothing about the token
            print(f"note: the saved login could not be checked ({error}); using its token")
        else:
            if login.status is not LoginStatus.CONNECTED:
                print(f"note: the login handshake reads {login.status.value} ({login.message}); using its token")
        # The lock is taken only once the things that can still refuse this run have been checked: a process that
        # takes the lock and then exits is a start the reader was told had worked.
        lock = SingletonLock(Worker(state_dir).lock)
        if not lock.acquire(wait=0.2):  # a probe takes the lock for an instant; a short wait tells the two apart
            print("another bridge is running; `zettcode-weixin status` says which, `stop` ends it")
            return 3
        guard = DaemonGuard(
            workspace=Path(state.workspace or Path.cwd()),
            state=state,
            model=state.model or None,
            effort=state.effort or None,
            permission=state.permission or "full",
            name="weixin bridge",
        )
        await link.start()
        if not await link.connected():
            print("warning: the session broker is not reachable; the first message will say so")
        bridge = Bridge(
            im=client,
            guard=guard,
            link=link,
            state=state,
            path=state_dir / "state.json",
            settings=BridgeSettings(
                allow=frozenset(state.allow),
                allow_all=state.allow_all,
            ),
            error=_log,
        )
        _on_signals(bridge.stop)
        print(f"weixin bridge running for {state.workspace or Path.cwd()}; ctrl-c stops it")
        if state.allow_all:
            print("allows anyone who can message the bot")
        elif state.allow:
            print(f"allows: {', '.join(state.allow)}")
        else:
            print("allows nobody yet: each message is refused and names the id to allow")
        print(f"daemon session: {state.session_id or '(starts on the first message)'}")
        await bridge.run()
        return 0
    finally:
        await link.close()
        await client.aclose()
        if lock is not None:
            lock.release()


def _bridge_id(state_dir: Path) -> str:
    """Return the broker id of the bridge in one directory: stable per bridge, different between two of them.

    Two bridges — two WeChat accounts, or a stale worker on another ``--state-dir`` — would otherwise claim the
    same session on the broker, and the second would see every send refused as if it were the agent's fault.
    """
    import hashlib

    return "im-weixin-" + hashlib.sha1(str(state_dir.resolve()).encode("utf-8")).hexdigest()[:8]


# -- settings ------------------------------------------------------------------------------------------
def _apply_settings(state: object, arguments: argparse.Namespace) -> None:
    """Take the flags that were given and leave the ones that were not: a re-scan renews the connection, not the
    decisions.

    ``None`` is how the parser says "not given" for every one of these, which is why ``--allow`` defaults to
    ``None`` rather than to an empty list: an empty list means "nobody is allowed", and forgetting a flag must not
    mean that.
    """
    if arguments.workspace is not None:
        state.workspace = str(Path(arguments.workspace).expanduser().resolve())  # type: ignore[attr-defined]
    elif not state.workspace:  # type: ignore[attr-defined]
        state.workspace = str(Path.cwd())  # type: ignore[attr-defined]
    if arguments.model is not None:
        state.model = arguments.model  # type: ignore[attr-defined]
    if arguments.effort is not None:
        state.effort = arguments.effort  # type: ignore[attr-defined]
    if arguments.permission is not None:
        state.permission = arguments.permission  # type: ignore[attr-defined]
    elif not state.permission:  # type: ignore[attr-defined]
        state.permission = "full"  # type: ignore[attr-defined]
    if arguments.allow is not None:
        state.allow = list(arguments.allow)  # type: ignore[attr-defined]
    if arguments.allow_all is not None:
        state.allow_all = bool(arguments.allow_all)  # type: ignore[attr-defined]


def _start(state_dir: Path) -> int:
    """Start the background process with the login that is already stored: what a scan ends with, without the scan."""
    from ..state import BridgeState

    state = BridgeState.load(state_dir / "state.json")
    if not state.logged_in:
        print(f"no login in {state_dir}: run `zettcode-weixin` to scan one")
        return 2
    worker = Worker(state_dir)
    if worker.running():
        print(f"the bridge is already running (pid {worker.pid()})")
        return 0
    try:
        pid = worker.start(command("--state-dir", str(state_dir)))
    except RuntimeError as error:
        print(f"the bridge did not start: {error}")
        return 3
    print(
        f"bridge running (pid {pid}); allows: {', '.join(state.allow) or ('anyone' if state.allow_all else 'nobody')}"
    )
    return 0


def _setting_problem(arguments: argparse.Namespace, state: object) -> str:
    """Return what is wrong with the settings asked for, or an empty string.

    Checked before anything is stopped or written: a level or a model the machine does not have would otherwise be
    saved and fail on the next message, with the old daemon already gone and a chat waiting for an answer.
    """
    from zettcode.sdk.models import list_models

    if arguments.workspace is not None and not Path(arguments.workspace).expanduser().is_dir():
        return f"no such directory: {arguments.workspace}"
    try:
        models = list(list_models())
    except (OSError, ValueError) as error:
        return f"the model configuration cannot be read: {error}"
    wanted = arguments.model if arguments.model is not None else getattr(state, "model", "")
    chosen = None
    if wanted:
        matched = [info for info in models if info.name == wanted or info.model == wanted]
        if len(matched) != 1:
            return f"no model named {wanted!r}; `zettcode daemon model` lists the ones there are"
        chosen = matched[0]
    elif models:
        chosen = models[0]
    if arguments.effort is not None and chosen is not None:
        levels = [str(level) for level in chosen.efforts]
        if arguments.effort not in levels:
            return f"{chosen.name} takes {', '.join(levels) or 'no level'}, not {arguments.effort!r}"
    return ""


def _set(arguments: argparse.Namespace, state_dir: Path) -> int:
    """Write the settings a daemon is started with, and put them in force now.

    Two things keep the old values alive if this only wrote the file: a running daemon was started with the old
    level, and the background process read the file once at its own start. So the daemon is stopped (the bridge
    starts it again with the stored settings on the next message) and the process is restarted.

    The daemon is stopped *before* the file is written, and a daemon that is busy stops the whole command: it would
    otherwise keep running with the old settings while the file describes new ones, and the bridge would find it
    alive and never start the one the reader asked for.
    """
    import asyncio

    from zettcode.sdk.daemons import stop_daemon
    from zettcode.sdk.errors import ConfigurationError, SessionNotFoundError

    from ..state import BridgeState

    state = BridgeState.load(state_dir / "state.json")
    if not state.logged_in:
        print(f"no login in {state_dir}: run `zettcode-weixin` to scan one")
        return 2
    problem = _setting_problem(arguments, state)
    if problem:
        print(f"not changed: {problem}")
        return 2

    worker = Worker(state_dir)
    was_running = worker.running()
    if was_running:
        print(worker.stop())
        if worker.running():
            # It would read the old file and write its own copy back over the new one.
            print("not changed: the bridge did not stop; stop it by hand and run the command again")
            return 3
    if state.session_id and not arguments.keep_daemon:
        try:
            said = asyncio.run(stop_daemon(state.session_id, keep=True))
        except SessionNotFoundError:
            said = "no daemon was running for it"
        except ConfigurationError as error:
            print(f"not changed: the daemon is still doing what it was: {error}")
            if was_running:
                _restart_worker(worker, state_dir)
            return 3
        except Exception as error:  # noqa: BLE001 - any other failure is still a stop that did not happen
            print(f"not changed: the daemon could not be stopped: {error}")
            if was_running:
                _restart_worker(worker, state_dir)
            return 3
        print(f"daemon     {said}")

    previous_workspace = state.workspace
    _apply_settings(state, arguments)
    if state.workspace != previous_workspace:
        # A session lives in one workspace; carrying its id over would resume a conversation that is not there.
        state.session_id = ""
        state.chats.clear()
    dropped = _drop_incompatible_effort(state)
    state.save()
    print(f"workspace  {state.workspace or Path.cwd()}")
    print(f"model      {state.model or '(the first configured)'}")
    print(f"effort     {state.effort or '(the middle of what the model takes)'}")
    print(f"shell      {state.permission}")
    if dropped:
        print(f"note       {dropped}")
    if state.allow_all:
        print("allows     anyone who can message the bot")
    else:
        print(f"allows     {', '.join(state.allow) or 'nobody'}")

    if was_running:
        pid = _restart_worker(worker, state_dir)
        if pid is None:
            return 3
        print(f"bridge     running (pid {pid})")
    else:
        print("bridge     not running; `zettcode-weixin start` reads the new settings")
    return 0


def _drop_incompatible_effort(state: object) -> str:
    """Clear a stored level the model it now runs on does not take, and say so; return an empty string otherwise.

    A level belongs to a model. Keeping ``high`` after moving to a model that stops at ``low`` would fail at the
    next start, with the old daemon already gone — so the level goes, and the middle of the new model's list
    applies instead.
    """
    from zettcode.sdk.models import list_models

    effort = getattr(state, "effort", "")
    if not effort:
        return ""
    try:
        models = list(list_models())
    except (OSError, ValueError):
        return ""
    wanted = getattr(state, "model", "")
    chosen = next((info for info in models if wanted and (info.name == wanted or info.model == wanted)), None)
    if chosen is None:
        chosen = models[0] if models else None
    if chosen is None:
        return ""
    levels = [str(level) for level in chosen.efforts]
    if effort in levels:
        return ""
    state.effort = ""  # type: ignore[attr-defined]
    return f"the level {effort!r} is not one {chosen.name} takes ({', '.join(levels) or 'none'}), so it is unset"


def _restart_worker(worker: Worker, state_dir: Path) -> int | None:
    """Start the background process again and return its pid, or say why it did not start."""
    try:
        pid = worker.start(command("--state-dir", str(state_dir)))
    except RuntimeError as error:
        print(f"the bridge did not start again: {error}")
        return None
    return pid


def _on_signals(stop: object) -> None:
    """Stop the bridge on ctrl-c and on the signal a stop sends, whatever this platform offers."""
    loop = asyncio.get_running_loop()
    for number in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(number, stop)  # type: ignore[arg-type]
        except (NotImplementedError, RuntimeError, ValueError):  # pragma: no cover - Windows, and not the main thread
            with contextlib.suppress(ValueError, OSError):
                signal.signal(number, lambda *_: stop())  # type: ignore[operator]


def _log(said: str) -> None:
    """Say one thing where a background process's reader can find it."""
    print(said, flush=True)


# -- status, stop, logs --------------------------------------------------------------------------------
def _status(state_dir: Path) -> int:
    """Say whether a bridge is running and what it knows."""
    from ..state import BridgeState

    worker = Worker(state_dir)
    state = BridgeState.load(state_dir / "state.json")
    print(f"bridge:    running (pid {worker.pid()})" if worker.running() else "bridge:    not running")
    print(f"wechat:    {'logged in' if state.logged_in else 'not logged in'}")
    print(f"workspace: {state.workspace or '(not recorded)'}")
    print(f"session:   {state.session_id or '(the daemon starts on the first message)'}")
    short = state.cursor[:12] + ("\u2026" if len(state.cursor) > 12 else "") if state.cursor else "(none)"
    print(f"cursor:    {short}")
    if state.allow_all:
        print("allows:    everyone who can message the bot")
    elif state.allow:
        print(f"allows:    {', '.join(state.allow)}")
    else:
        print("allows:    nobody yet")
    print(f"state:     {state_dir / 'state.json'}")
    print(f"log:       {worker.log}")
    return 0


__all__ = ["DEFAULT_DIR", "LOGIN_TIMEOUT", "POLL", "build_parser", "main"]


if __name__ == "__main__":  # the background process runs this module, not the console script
    sys.exit(main())
