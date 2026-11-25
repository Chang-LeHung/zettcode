"""Fixed, standalone Python payload sent by OpenSSH; only the standard library is used remotely."""

from __future__ import annotations

import base64
import json
import math
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

MAX_FILE = 16 * 1024 * 1024
MAX_OUTPUT = 50 * 1024
MAX_IMAGE = 4 * 1024 * 1024
MAX_REQUEST = 4 * 1024 * 1024
TRUNCATED = "\n... [truncated; narrow the request]"


def text(value: object, name: str, *, empty: bool = False, nul: bool = False) -> str:
    if not isinstance(value, str) or (not nul and "\x00" in value) or (not empty and not value):
        raise ValueError(f"{name} must be {'text' if empty else 'nonempty text'}" + ("" if nul else " without NUL"))
    return value


def integer(value: object, name: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer from {minimum} to {maximum}")
    return value


def boolean(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{name} must be true or false")
    return value


def duration(value: object) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 < value <= 120
    ):
        raise ValueError("timeout_seconds must be a finite number greater than 0 and at most 120")
    return float(value)


def prefix(value: str, size: int = MAX_OUTPUT) -> str:
    return value.encode("utf-8")[:size].decode("utf-8", errors="ignore")


def located(file_path: str) -> Path:
    return Path(text(file_path, "file_path")).expanduser().resolve()


def regular(path: Path) -> None:
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError(f"Not a regular file: {path}")


def contents(path: Path, maximum: int = MAX_FILE) -> bytes:
    regular(path)
    with path.open("rb") as source:
        data = source.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError(f"File exceeds {maximum} bytes: {path}")
    return data


def read_file(file_path: str, offset: int = 1, limit: int = 2000) -> str:
    integer(offset, "offset", 1, 1_000_000)
    integer(limit, "limit", 1, 2000)
    path = located(file_path)
    regular(path)
    rendered: list[str] = []
    used = 0
    # Universal newlines retain vertical tabs/Unicode separators as content. Bound even
    # skipped lines: an enormous unterminated log line must not be materialized in memory.
    with path.open("r", encoding="utf-8", newline=None) as source:
        for _ in range(offset - 1):
            while True:
                chunk = source.readline(MAX_OUTPUT + 1)
                if not chunk:
                    return ""
                if chunk.endswith("\n"):
                    break
        for number in range(offset, offset + limit):
            line = source.readline(MAX_OUTPUT + 1)
            if not line:
                break
            row = f"{number}\t{line}"
            size = len(row.encode("utf-8"))
            if used + size > MAX_OUTPUT:
                if not rendered:
                    return prefix(row) + (
                        "\n... [line truncated; use ssh__bash for a bounded slice of this remote line]"
                    )
                return "".join(rendered) + f"\n... [more lines; continue with offset={number}]"
            rendered.append(row)
            used += size
        if source.read(1):
            rendered.append(f"\n... [more lines; continue with offset={offset + len(rendered)}]")
    return "".join(rendered)


def read(file_path: str, offset: int = 1, limit: int = 2000) -> Any:
    integer(offset, "offset", 1, 1_000_000)
    integer(limit, "limit", 1, 2000)
    path = located(file_path)
    regular(path)
    with path.open("rb") as source:
        signature = source.read(16)
    media = None
    if signature.startswith(b"\x89PNG\r\n\x1a\n"):
        media = "image/png"
    elif signature.startswith(b"\xff\xd8\xff"):
        media = "image/jpeg"
    elif signature.startswith((b"GIF87a", b"GIF89a")):
        media = "image/gif"
    elif signature.startswith(b"RIFF") and signature[8:12] == b"WEBP":
        media = "image/webp"
    if media is None:
        return read_file(file_path, offset, limit)
    if path.stat().st_size > MAX_IMAGE:
        raise ValueError(f"Image exceeds {MAX_IMAGE} bytes")
    return {
        "image": base64.b64encode(contents(path, MAX_IMAGE)).decode("ascii"),
        "media_type": media,
        "name": path.name,
    }


def atomic(path: Path, content: str) -> None:
    text(content, "content", empty=True, nul=True)
    if len(content.encode("utf-8")) > MAX_FILE:
        raise ValueError(f"Content exceeds {MAX_FILE} bytes")
    if path.exists() and not path.is_file():
        raise ValueError(f"Not a regular file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".zettcode-ssh-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as target:
            target.write(content)
            target.flush()
            os.fsync(target.fileno())
        if path.exists():
            os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_file(file_path: str, content: str) -> str:
    path = located(file_path)
    exists = path.exists()
    atomic(path, content)
    return f"{'Wrote' if exists else 'Created'} {path}"


def edit(file_path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
    text(old_string, "old_string", nul=True)
    text(new_string, "new_string", empty=True, nul=True)
    boolean(replace_all, "replace_all")
    path = located(file_path)
    original = contents(path).decode("utf-8")
    count = original.count(old_string)
    if count == 0:
        raise ValueError(
            "old_string not found. Read the file again and copy the exact whitespace and line endings; "
            "omit the numbered-line prefixes from old_string."
        )
    if count != 1 and not replace_all:
        raise ValueError(f"Exact edit requires a unique match (found {count}); use replace_all only intentionally")
    atomic(path, original.replace(old_string, new_string))
    return f"Replaced {count} occurrence{'s' if count != 1 else ''} in {path}"


def matches(pattern: str) -> Iterator[tuple[Path, str]]:
    """Path.glob semantics on Python 3.10: hidden entries included, ** does not follow directory links."""
    candidate = Path(pattern).expanduser()
    absolute = candidate.is_absolute()
    root = Path(candidate.anchor) if absolute else Path.cwd()
    expression = candidate.relative_to(root).as_posix() if absolute else candidate.as_posix()
    for match in root.glob(expression):
        shown = match.as_posix() if absolute else Path(os.path.relpath(match, root)).as_posix()
        yield match, shown


def glob(pattern: str, max_results: int = 200) -> str:
    text(pattern, "pattern")
    integer(max_results, "max_results", 1, 5000)
    results: list[str] = []
    used = 0
    # Stop gathering before sorting: recursive patterns must not materialize an unbounded tree.
    for _, match in matches(pattern):
        size = len(match.encode("utf-8")) + 1
        if len(results) >= max_results or used + size > MAX_OUTPUT:
            return "\n".join(sorted(results)) + TRUNCATED
        results.append(match)
        used += size
    return "\n".join(sorted(results))


def grep(pattern: str, file_pattern: str = "**/*", case_sensitive: bool = True, max_results: int = 200) -> str:
    text(pattern, "pattern")
    text(file_pattern, "file_pattern")
    boolean(case_sensitive, "case_sensitive")
    integer(max_results, "max_results", 1, 5000)
    expression = re.compile(pattern, 0 if case_sensitive else re.IGNORECASE)
    results: list[str] = []
    used = 0
    for path, match in matches(file_pattern):
        if not path.is_file() or path.stat().st_size > MAX_FILE:
            continue
        try:
            lines = contents(path).decode("utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(lines, 1):
            found = expression.search(line)
            if found is None:
                continue
            row = f"{match}:{number}: {prefix(line[max(0, found.start() - 100) :], 2000)}"
            size = len(row.encode("utf-8")) + 1
            if len(results) >= max_results or used + size > MAX_OUTPUT:
                return "\n".join(results) + TRUNCATED
            results.append(row)
            used += size
    return "\n".join(results)


class CommandFailed(RuntimeError):
    """A failed remote shell command, with its bounded combined stdout/stderr."""


def bash(command: str, timeout_seconds: float = 60, work_dir: str | None = None) -> str:
    text(command, "command")
    if not command.strip():
        raise ValueError("Shell command cannot be blank")
    timeout = duration(timeout_seconds)
    directory = Path.cwd() if work_dir is None else located(work_dir)
    # Output is drained continuously with a bounded buffer, not communicate() over arbitrary remote output.
    import selectors
    import time

    process = subprocess.Popen(
        ["/bin/bash", "-c", command],
        cwd=directory,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    assert process.stdout is not None and process.stderr is not None
    output = bytearray()
    errors = bytearray()
    truncated = False
    deadline = time.monotonic() + timeout
    selector = selectors.DefaultSelector()
    timed_out = False
    try:
        selector.register(process.stdout, selectors.EVENT_READ, output)
        selector.register(process.stderr, selectors.EVENT_READ, errors)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            for key, _ in selector.select(min(remaining, 0.1)):
                chunk = os.read(key.fd, 8192)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                room = MAX_OUTPUT - len(output) - len(errors)
                key.data.extend(chunk[:room])
                truncated = truncated or len(chunk) > room
        if not timed_out:
            try:
                process.wait(timeout=max(0.001, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                timed_out = True
    finally:
        # Bound descendants even if the shell exits before them. Pipes retained by background
        # children must not extend either the operation deadline or cleanup indefinitely.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        finally:
            process.stdout.close()
            process.stderr.close()
            selector.close()
    sections = []
    if output:
        sections.append(output.decode("utf-8", errors="replace"))
    if errors:
        sections.append("[stderr]\n" + errors.decode("utf-8", errors="replace"))
    result = "\n".join(sections) + (TRUNCATED if truncated else "")
    details = f"[remote exit code: {process.returncode}]\n{result}"
    if timed_out:
        raise CommandFailed(f"Remote bash timed out after {timeout:g} seconds\n{details}")
    if process.returncode != 0:
        raise CommandFailed(f"Command exited with code {process.returncode}\n{details}")
    return result


def ping() -> str:
    return str(Path.cwd())


OPERATIONS: dict[str, Callable[..., Any]] = {
    "ping": ping,
    "read": read,
    "read_file": read_file,
    "write_file": write_file,
    "edit": edit,
    "bash": bash,
    "glob": glob,
    "grep": grep,
}


def dispatch(request: dict[str, Any]) -> Any:
    operation = request["operation"]
    if operation not in OPERATIONS:
        raise ValueError("Unknown remote operation")
    workspace = text(request["workspace"], "workspace")
    if not workspace.startswith("/"):
        raise ValueError("Remote workspace must be absolute")
    os.chdir(workspace)
    arguments = request["arguments"]
    if not isinstance(arguments, dict):
        raise ValueError("Tool arguments must be an object")
    return OPERATIONS[operation](**arguments)


def serve() -> None:
    """Process bounded newline-framed requests until the owning SSH channel closes."""

    def expired(signum: int, frame: Any) -> None:
        raise TimeoutError("Remote operation exceeded 125 seconds")

    signal.signal(signal.SIGALRM, expired)
    output = sys.stdout.buffer
    while True:
        raw = sys.stdin.buffer.readline(MAX_REQUEST + 2)
        if not raw:
            return
        if len(raw) > MAX_REQUEST + 1 or not raw.endswith(b"\n"):
            return  # A corrupt/oversized frame cannot be safely resynchronized.
        signal.alarm(125)
        request: dict[str, Any] = {}
        try:
            request = json.loads(raw)
            result = dispatch(request)
            response = {"ok": True, "result": result, "id": request["id"]}
        except Exception as error:
            size = MAX_OUTPUT + 1000 if isinstance(error, CommandFailed) else 4000
            response = {"ok": False, "error": prefix(f"{type(error).__name__}: {error}", size), "id": request.get("id")}
        finally:
            signal.alarm(0)
        output.write(json.dumps(response, ensure_ascii=False).encode("utf-8") + b"\n")
        output.flush()


def main() -> None:
    # The transport timeout is the outer bound. The remote alarm also bounds regexes and filesystem traversal
    # if the SSH connection is lost; bash has its own, shorter deadline and kills its process group.
    def expired(signum: int, frame: Any) -> None:
        raise TimeoutError("Remote operation exceeded 125 seconds")

    signal.signal(signal.SIGALRM, expired)
    signal.alarm(125)
    try:
        raw = sys.stdin.buffer.read(MAX_REQUEST + 1)
        if len(raw) > MAX_REQUEST:
            raise ValueError("Remote request exceeds 4 MiB")
        result = dispatch(json.loads(raw))
        response = {"ok": True, "result": result}
    except Exception as error:
        # Shell failures carry the same bounded output as successes, not just an exception summary.
        size = MAX_OUTPUT + 1000 if isinstance(error, CommandFailed) else 4000
        response = {"ok": False, "error": prefix(f"{type(error).__name__}: {error}", size)}
    sys.stdout.buffer.write(json.dumps(response, ensure_ascii=False).encode("utf-8"))
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    serve() if "--worker" in sys.argv else main()
