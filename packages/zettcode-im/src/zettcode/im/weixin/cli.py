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
        ("run", "run the bridge in this terminal (what the background process does)"),
        ("status", "say whether a bridge is running and what it is doing"),
        ("stop", "stop the background process"),
        ("logs", "print the end of the background process's log"),
    ):
        sub = commands.add_parser(name, help=help_line, description=help_line)
        _common(sub, login=name == "login", run=name == "run")
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
            default=Path.cwd(),
            help="directory the agent works in (default: the current one)",
        )
        sub.add_argument("--model", default="", help="the model the daemon runs on (default: the first configured)")
        sub.add_argument("--effort", default="", help="the reasoning level (default: the model's own)")
        sub.add_argument(
            "--permission",
            choices=("deny", "safe", "full"),
            default="safe",
            help="the daemon's shell level (default: safe, every command in a sandbox)",
        )
        sub.add_argument(
            "--allow", action="append", default=[], help="a sender id allowed to drive the agent; repeatable"
        )
        sub.add_argument(
            "--allow-all",
            action="store_true",
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
    if worker.running():
        print(worker.stop(), "\u2014 a new scan starts a new process")
        if worker.running():
            # The old process is still writing the same state file with the old token and cursor; saving this
            # login under it would be undone as soon as it saved again.
            print("the old bridge did not stop; nothing was changed. Stop it by hand and run the command again.")
            return 3
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
    # A new login is a new connection: the cursor and the reply contexts belong to the old one. The session and
    # the messages already answered stay, so the conversation and its history carry over.
    state.cursor = ""
    state.chats.clear()
    state.workspace = str(Path(arguments.workspace).expanduser().resolve())
    state.model = arguments.model or ""
    state.effort = arguments.effort or ""
    state.permission = arguments.permission
    state.allow = list(arguments.allow)
    state.allow_all = bool(arguments.allow_all)
    state.save()

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
        try:
            handshake = LoginHandshake.model_validate(state.handshake)
            login = await client.is_login(handshake)
        except Exception as error:  # noqa: BLE001 - a handshake this build cannot read is a login to redo
            print(f"the saved login cannot be checked: {error}. Run `zettcode-weixin` again.")
            return 3
        if login.status in (LoginStatus.FAILED, LoginStatus.EXPIRED):
            print(f"the WeChat login has ended: {login.message}. Run `zettcode-weixin` again.")
            return 3
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
            permission=state.permission or "safe",
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
