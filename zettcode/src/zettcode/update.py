"""Notice a newer ZettCode on PyPI, and install it when the reader asks.

The check itself is never on the startup path: a background task asks PyPI once a day and leaves what it found in
``~/.zettcode/update.json``. The next start reads that file — no network, nothing to wait for — and offers the version
it names, unless the reader has already skipped that one. The upgrade that follows a "yes" does block, on purpose:
the reader asked for it, so it asks PyPI what is newest at that moment, installs from PyPI's own index, and the window
takes no input until it is done.

An upgrade is only believed once it has been checked. A package manager that exits 0 has
not necessarily installed anything (``uv tool upgrade`` answers "Nothing to upgrade" with 0, and so
does a pip whose index has not listed the release yet), so after it runs the installed version is
read back from the interpreter that was upgraded and written to the same file. What the file says
is what the next start trusts: an upgrade that did not take is reported as that, not as done, and
one that did is not offered again.

Every failure means "no news". A machine with no network, a proxy that eats the
request, an index that answers with something unexpected: none of them may
become the reason a session fails to open, so the check swallows what it cannot
use and leaves the stored state alone.
"""

from __future__ import annotations

import asyncio
import json
import os
import ssl
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from shutil import which
from tempfile import NamedTemporaryFile
from typing import Any, TypeVar

from . import __version__
from .paths import DEFAULT_UPDATE_FILE

Result = TypeVar("Result")

#: PyPI's JSON API for this project; ``info.version`` is the newest release. Named for the API it is, beside the
#: simple index below, so the two cannot be mistaken for one another.
JSON_API_URL = "https://pypi.org/pypi/zettcode/json"

#: PyPI's package index, which the upgrade is pointed at explicitly. The metadata above comes from PyPI, so the
#: download has to as well: a mirror configured on this machine can lag behind it by hours, and the package manager
#: then reports "already satisfied" for a release that has existed for a while. A reader who wants the mirror can
#: still install by hand.
SIMPLE_INDEX = "https://pypi.org/simple"

#: Seconds the request may take before it is abandoned. Generous on purpose: a
#: corporate proxy is routine here, and the check runs in the background, so a
#: slow answer costs a thread rather than a frame. A start never notices either way.
TIMEOUT = 10.0

#: How long one answer is trusted: a start inside the window reads the file only.
CHECK_INTERVAL = timedelta(hours=24)


def version_key(value: str) -> tuple[int, ...]:
    """Return a comparable key for a version such as ``0.1.2``.

    Only the leading digits of each dot-separated part are read, so a release
    candidate (``0.2.0rc1``) keys the same as the release it leads to and is
    never offered over it.
    """
    parts: list[int] = []
    for piece in value.strip().lstrip("vV").split("."):
        leading = ""
        for character in piece:
            if not character.isdigit():
                break
            leading += character
        parts.append(int(leading) if leading else 0)
    return tuple(parts)


def is_newer(candidate: str, current: str) -> bool:
    """Return whether ``candidate`` is a later release than ``current``."""
    return version_key(candidate) > version_key(current)


def _text(value: object) -> str | None:
    """Return a stored string, or ``None`` for anything else."""
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _moment(value: object) -> datetime | None:
    """Return a stored timestamp as an aware datetime, or ``None``."""
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)


@dataclass(frozen=True, slots=True)
class UpdateState:
    """What the last check found, what the reader has dismissed, and what an upgrade installed.

    Attributes:
        checked_at: When the index was last asked, aware and in UTC; ``None``
            before the first successful check.
        latest: Newest release the index named, if any.
        skipped: Version the reader said not to ask about again.
        installed: Version an upgrade was *confirmed* to have installed, read back from the
            environment afterwards; ``None`` until one has been.
        installed_by: The interpreter that upgrade ran in. A record is only about that interpreter.
        noted: Version whose mismatch with the running program has already been explained, so the
            explanation is given once and not at every start.
    """

    checked_at: datetime | None = None
    latest: str | None = None
    skipped: str | None = None
    installed: str | None = None
    installed_by: str | None = None
    noted: str | None = None

    @property
    def stale(self) -> bool:
        """Return whether the stored answer is old enough to ask the index again."""
        if self.checked_at is None:
            return True
        return datetime.now(timezone.utc) - self.checked_at >= CHECK_INTERVAL

    def shadowed_by(self, current: str = __version__, executable: str | None = None) -> str | None:
        """Return the version an upgrade installed here that this process is not running, if any.

        A confirmed install newer than the running program, in the interpreter that is running it,
        means the upgrade worked and something else is supplying the code — an editable checkout, a
        ``PYTHONPATH`` — so offering the same upgrade again cannot change what runs. A record made
        by another interpreter says nothing about this one: that copy really is old.

        Args:
            current: Version of the running program.
            executable: Interpreter running it; defaults to this process's.
        """
        if self.installed is None or self.installed_by != (executable or sys.executable):
            return None
        return self.installed if is_newer(self.installed, current) else None

    def offer(self, current: str = __version__, executable: str | None = None) -> str | None:
        """Return the version worth offering, or ``None`` when there is nothing to say."""
        if self.latest is None or self.skipped == self.latest:
            return None
        if self.shadowed_by(current, executable) is not None:
            return None
        return self.latest if is_newer(self.latest, current) else None


async def in_background(work: Callable[[], Result]) -> Result:
    """Run one blocking call on a daemon thread and return what it produced.

    Not :func:`asyncio.to_thread`: that uses the loop's own executor, which is
    joined when the process exits, so a request still waiting on a slow proxy
    would hold the terminal open for as long as its timeout. This thread is left
    behind instead, because a check nobody is waiting for cannot matter once the
    session is gone.
    """
    loop = asyncio.get_running_loop()
    future: asyncio.Future[Result] = loop.create_future()

    def deliver(value: Result) -> None:
        """Resolve the awaiting coroutine, unless it already went away."""
        if not future.done():
            future.set_result(value)

    def fail(error: BaseException) -> None:
        """Report why the call produced nothing, for the same reason."""
        if not future.done():
            future.set_exception(error)

    def hand_over(callback: Callable[[Any], None], argument: Any) -> None:
        """Pass the outcome to the loop, unless the loop is gone.

        The thread is left running on purpose when the session ends, so its answer can
        arrive after the loop has been closed — and ``call_soon_threadsafe`` then raises.
        A daemon thread that raises prints a traceback, and one that does so while the
        interpreter is shutting down can take the whole process down with it: the
        standard error stream's lock cannot be taken, and Python aborts. Nobody is
        waiting for this answer any more, so dropping it is the whole of the handling.
        """
        try:
            loop.call_soon_threadsafe(callback, argument)
        except RuntimeError:
            pass

    def run() -> None:
        try:
            value = work()
        except BaseException as error:  # noqa: BLE001 - handed to the awaiting caller
            hand_over(fail, error)
        else:
            hand_over(deliver, value)

    threading.Thread(target=run, name="zettcode-background", daemon=True).start()
    return await future


def read_state(path: Path) -> UpdateState:
    """Return what the last check left, or an empty state when nothing is readable."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return UpdateState()
    if not isinstance(raw, dict):
        return UpdateState()
    return UpdateState(
        checked_at=_moment(raw.get("checked_at")),
        latest=_text(raw.get("latest")),
        skipped=_text(raw.get("skipped")),
        installed=_text(raw.get("installed")),
        installed_by=_text(raw.get("installed_by")),
        noted=_text(raw.get("noted")),
    )


def write_state(state: UpdateState, path: Path) -> None:
    """Write the state in one replace, so a crash cannot leave half a file."""
    payload = {
        "checked_at": state.checked_at.isoformat() if state.checked_at is not None else None,
        "latest": state.latest,
        "skipped": state.skipped,
        "installed": state.installed,
        "installed_by": state.installed_by,
        "noted": state.noted,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def fetch_latest(url: str = JSON_API_URL, *, timeout: float = TIMEOUT) -> str:
    """Return the newest release the index reports, raising when it cannot."""
    request = urllib.request.Request(url, headers={"User-Agent": f"zettcode/{__version__}"})
    try:
        with urllib.request.urlopen(  # noqa: S310 - the URL is ours
            request, timeout=timeout, context=ssl_context()
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as error:
        raise RuntimeError(f"could not read {url}: {error}") from error
    latest = payload.get("info", {}).get("version") if isinstance(payload, dict) else None
    if not isinstance(latest, str) or not latest.strip():
        raise RuntimeError(f"{url} answered without a version")
    return latest.strip()


def ssl_context() -> ssl.SSLContext:
    """Return the trust store to verify the index against.

    The platform's own, through ``truststore``, rather than the roots bundled
    with Python: a machine behind a corporate proxy — which is what an internal
    gateway usually means — cannot verify anything against the bundled set, and
    the system store is what every other program on it already trusts. The
    import is local because the check runs in a worker thread, and a client that
    never asks about updates should not pay for it at import time.
    """
    try:
        import truststore
    except ImportError:  # pragma: no cover - truststore ships with the runtime deps
        return ssl.create_default_context()
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


async def check_for_update(
    path: Path,
    *,
    fetch: Callable[[], str] = fetch_latest,
    now: Callable[[], datetime] | None = None,
) -> UpdateState | None:
    """Ask the index in a thread and store what it said.

    Args:
        path: File the answer is written to.
        fetch: Supplies the newest version; injectable so tests stay offline.
        now: Clock for the check timestamp; defaults to UTC now.

    Returns:
        The state that was written, or ``None`` when the stored answer was still
        fresh, or the index could not be read.
    """
    state = read_state(path)
    if not state.stale:
        return None
    try:
        latest = await in_background(fetch)
    except Exception:
        # Offline, a proxy in the way, an index that answered oddly: the next
        # start tries again, and this one says nothing about it.
        return None
    moment = (now or (lambda: datetime.now(timezone.utc)))()
    written = replace(state, checked_at=moment, latest=latest)
    write_state(written, path)
    return written


def installed_by_uv_tool() -> bool:
    """Return whether this interpreter lives in a ``uv tool`` environment.

    ``uv`` leaves a ``uv-receipt.toml`` at the root of every tool environment, wherever
    ``UV_TOOL_DIR`` put it, which is the one thing that is not a guess. The path is the fallback,
    and it is read as given: a tool environment's ``python`` is a link to the interpreter it was
    built from, and resolving it names that interpreter's directory instead, which has no ``tools``
    in it. That is how a real ``uv tool`` install used to be taken for a pip one, and handed a
    ``pip install --upgrade`` in an environment that has no pip.
    """
    if (Path(sys.prefix) / "uv-receipt.toml").is_file():
        return True
    parts = Path(sys.executable).parts
    return "uv" in parts and "tools" in parts


def upgrade_command() -> tuple[str, ...]:
    """Return the command that replaces this installation with the newest release.

    ``uv tool upgrade`` when uv installed ZettCode that way, ``pip`` for the
    interpreter running this process otherwise. Both are pointed at PyPI's own index: the newest version was read
    from PyPI, and installing through whatever mirror the machine has configured would ask for a release that index
    may not list yet. The panel shows the command before it runs, so a wrong guess is visible rather than
    surprising.
    """
    if installed_by_uv_tool() and which("uv") is not None:
        # `--index-url` rather than the newer `--default-index`: current uv still takes the old spelling, and an
        # older one only has that, so an upgrade that worked before this flag keeps working.
        return ("uv", "tool", "upgrade", "zettcode", "--index-url", SIMPLE_INDEX)
    return (sys.executable, "-m", "pip", "install", "--upgrade", "--index-url", SIMPLE_INDEX, "zettcode")


async def run_upgrade(command: Sequence[str] | None = None, *, timeout: float = 600.0) -> tuple[bool, str]:
    """Run the upgrade in a thread and return whether it worked and what it said.

    The output is captured rather than painted: this runs while the terminal
    belongs to the frame, and a package manager's progress bars would corrupt it.
    """
    argv = tuple(command) if command is not None else upgrade_command()
    try:
        result = await in_background(
            lambda: subprocess.run(
                argv,
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=timeout,
                check=False,
            )
        )
    except (OSError, subprocess.SubprocessError) as error:
        return False, str(error)
    output = f"{result.stdout or ''}{result.stderr or ''}".strip()
    return result.returncode == 0, output


#: What a fresh interpreter is asked to print: the version of the installed distribution, which is
#: what the next start will run, whatever this process was started with.
INSTALLED_PROBE = "from importlib.metadata import version; print(version('zettcode'))"


async def installed_version(executable: str | None = None, *, timeout: float = 60.0) -> str | None:
    """Return the version of ZettCode installed for an interpreter, read from a fresh process.

    The running process cannot answer: it imported the code it started with, which is the version
    that is being replaced. A new process reads what is on disk now, which is what the next start
    will run. It is started from a neutral directory, because a start is not made from the workspace
    and a stray ``zettcode`` there must not answer for the install.

    Args:
        executable: The interpreter the upgrade ran in; defaults to this process's.
        timeout: Seconds before giving up.

    Returns:
        The version, or ``None`` when it could not be read — which is "unconfirmed", never "unchanged".
    """
    argv = (executable or sys.executable, "-c", INSTALLED_PROBE)
    try:
        result = await in_background(
            lambda: subprocess.run(
                argv,
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=timeout,
                check=False,
                cwd=tempfile.gettempdir(),
            )
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    lines = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    return lines[-1] if lines else None


def record_install(path: Path, version: str, executable: str | None = None) -> None:
    """Write down that an upgrade installed ``version``, keeping everything else the file says.

    Args:
        path: The state file.
        version: What :func:`installed_version` confirmed.
        executable: The interpreter it was confirmed for; defaults to this process's.
    """
    write_state(
        replace(read_state(path), installed=version, installed_by=executable or sys.executable, noted=None), path
    )


def running_from() -> str:
    """Return the directory the running program's code was loaded from."""
    return str(Path(__file__).resolve().parent)


def display_command(command: Sequence[str]) -> str:
    """Return the command the way a reader would type it.

    The pip fallback has to name an interpreter to be unambiguous
    (``/path/to/python -m pip ...``), and that path is both long enough to be
    clipped in a panel row and noise beside the ``pip install`` it stands for.
    Everything else is shown as it runs, including the index: the panel promises the command can be read before it
    runs, and which index it installs from is exactly what a reader deciding to accept it would want to see.
    """
    argv = list(command)
    if len(argv) > 2 and argv[1] == "-m" and Path(argv[0]).name.lower().startswith(("python", "pypy")):
        return " ".join(argv[2:])
    return " ".join(argv)


def _run_in_terminal(command: Sequence[str]) -> int:
    """Run the package manager with the reader's own terminal, so its progress is what they see."""
    try:
        return subprocess.run(list(command), check=False).returncode
    except OSError as error:
        print(f"could not run {display_command(command)}: {error}", file=sys.stderr)
        return 127


def _installed_now() -> str | None:
    """Read the installed version back from a fresh interpreter (see :func:`installed_version`)."""
    return asyncio.run(installed_version())


def update_program(
    *,
    current: str = __version__,
    path: Path | None = None,
    fetch: Callable[[], str] = fetch_latest,
    run: Callable[[Sequence[str]], int] = _run_in_terminal,
    read_installed: Callable[[], str | None] = _installed_now,
    say: Callable[[str], None] = print,
) -> int:
    """Install the newest release now, from the command line: what ``zettcode update`` does.

    The panel inside the program offers the same upgrade; this is for the reader who would rather ask for it
    than wait to be offered. It asks the index first, so a program that is already the newest says so and
    runs nothing; if the index cannot be reached it goes on regardless, because the package manager knows
    better than a failed request whether there is anything to install. The package manager's own output is
    shown, and its exit status is not believed on its own (see the module notes): the version is read back
    from a fresh interpreter, and only that is reported and recorded.

    Args:
        current: The version running now.
        path: The state file the confirmed install is written to; defaults to ``~/.zettcode/update.json``.
        fetch: Supplies the newest version; injectable so tests stay offline.
        run: Runs the upgrade command and returns its exit status.
        read_installed: Reads the version installed now, from outside this process.
        say: Where the report goes.

    Returns:
        The exit status: ``0`` when ZettCode is the newest release or was updated (or the update ran and the
        result could not be read back), ``1`` when the upgrade failed or left the old version.
    """
    say(f"ZettCode {current}")
    latest: str | None
    try:
        latest = fetch()
    except Exception:  # noqa: BLE001 - offline, a proxy, an odd answer: let the package manager decide
        latest = None
    if latest is not None and not is_newer(latest, current):
        say(f"already the newest release ({current})")
        return 0
    command = upgrade_command()
    say(f"updating{f' to {latest}' if latest else ''}: {display_command(command)}")
    status = run(command)
    if status != 0:
        say(f"the update failed (exit status {status}); run it yourself: {display_command(command)}")
        return 1
    installed = read_installed()
    if installed is None:
        say("the update ran, but the installed version could not be read back — check with `zettcode --version`")
        return 0
    if not is_newer(installed, current):
        if latest is not None:
            say(
                f"ZettCode is still {installed}, not {latest}: the release may be yanked, or the installer may have "
                f"been pinned to {installed}; try `uv tool install zettcode@latest`, or {display_command(command)}"
            )
        else:
            say(f"ZettCode is {installed}: there was nothing newer to install")
        return 1 if latest is not None else 0
    try:
        record_install(path if path is not None else DEFAULT_UPDATE_FILE, installed)
    except OSError:
        pass  # the install happened; failing to write it down must not make it look as if it had not
    say(f"updated {current} → {installed}; restart ZettCode to use it")
    return 0
