"""Notice a newer ZettCode on PyPI, without ever slowing a start down.

Nothing here is on the startup path: a background task asks PyPI once a day and
leaves what it found in ``~/.zettcode/update.json``. The next start reads that
file — no network, nothing to wait for — and offers the version it names, unless
the reader has already skipped that one.

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
import threading
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from shutil import which
from tempfile import NamedTemporaryFile
from typing import TypeVar

from . import __version__

Result = TypeVar("Result")

#: PyPI's JSON API for this project; ``info.version`` is the newest release.
INDEX_URL = "https://pypi.org/pypi/zettcode/json"

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
    """What the last check found, and what the reader has dismissed.

    Attributes:
        checked_at: When the index was last asked, aware and in UTC; ``None``
            before the first successful check.
        latest: Newest release the index named, if any.
        skipped: Version the reader said not to ask about again.
    """

    checked_at: datetime | None = None
    latest: str | None = None
    skipped: str | None = None

    @property
    def stale(self) -> bool:
        """Return whether the stored answer is old enough to ask the index again."""
        if self.checked_at is None:
            return True
        return datetime.now(timezone.utc) - self.checked_at >= CHECK_INTERVAL

    def offer(self, current: str = __version__) -> str | None:
        """Return the version worth offering, or ``None`` when there is nothing to say."""
        if self.latest is None or self.skipped == self.latest:
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

    def run() -> None:
        try:
            value = work()
        except BaseException as error:  # noqa: BLE001 - handed to the awaiting caller
            loop.call_soon_threadsafe(fail, error)
        else:
            loop.call_soon_threadsafe(deliver, value)

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
    )


def write_state(state: UpdateState, path: Path) -> None:
    """Write the state in one replace, so a crash cannot leave half a file."""
    payload = {
        "checked_at": state.checked_at.isoformat() if state.checked_at is not None else None,
        "latest": state.latest,
        "skipped": state.skipped,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def fetch_latest(url: str = INDEX_URL, *, timeout: float = TIMEOUT) -> str:
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
    """Return whether this interpreter lives in a ``uv tool`` environment."""
    parts = Path(sys.executable).resolve().parts
    return "uv" in parts and "tools" in parts


def upgrade_command() -> tuple[str, ...]:
    """Return the command that replaces this installation with the newest release.

    ``uv tool upgrade`` when uv installed ZettCode that way, ``pip`` for the
    interpreter running this process otherwise. The panel shows the command
    before it runs, so a wrong guess is visible rather than surprising.
    """
    if installed_by_uv_tool() and which("uv") is not None:
        return ("uv", "tool", "upgrade", "zettcode")
    return (sys.executable, "-m", "pip", "install", "--upgrade", "zettcode")


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


def display_command(command: Sequence[str]) -> str:
    """Return the command the way a reader would type it.

    The pip fallback has to name an interpreter to be unambiguous
    (``/path/to/python -m pip ...``), and that path is both long enough to be
    clipped in a panel row and noise beside the ``pip install`` it stands for.
    Everything else is shown as it runs.
    """
    argv = list(command)
    if len(argv) > 2 and argv[1] == "-m" and Path(argv[0]).name.lower().startswith(("python", "pypy")):
        return " ".join(argv[2:])
    return " ".join(argv)
