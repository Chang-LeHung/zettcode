"""The Python SDK and the TypeScript client are one interface in two languages, and this keeps them that way.

The rule is in ``docs/internal/clients.md``: the TypeScript name of an operation is the Python name in camelCase, in
the same group (``client.sessions``, ``client.session``). A public method that exists on one side only has to be
listed below with the reason, so a new method cannot drift in unnoticed: it either matches or someone says why not.

The TypeScript side is read from the source, not run, so this needs no Node.
"""

from __future__ import annotations

import inspect
import pathlib
import re

import pytest

from zettcode.sdk import client as sdk_client
from zettcode.sdk import errors as sdk_errors
from zettcode.sdk import events as sdk_events
from zettcode.sdk import session as sdk_session
from zettcode.sdk import types as sdk_types
from zettcode.server.app import FAILURES

ROOT = pathlib.Path(__file__).resolve().parents[2]
TS = ROOT / "clients/typescript/src"

#: Python public members with no TypeScript twin, and why.
PYTHON_ONLY: dict[str, dict[str, str]] = {
    "Client": {
        "aclose": "the process, not the API: a server client holds no resources",
        "closed": "the process, not the API",
        "config": "the server's configuration; `settings()` and `plugins()` report what a client may see",
        "workspace": "the server serves one workspace; `health()` names it",
        "effort": "read with `settings()`, which returns all four of these at once",
        "efforts": "read with `settings()`",
        "harness": "read with `settings()`",
        "model": "read with `settings()`",
        "permission": "read with `settings()`",
        "permissions": "read with `settings()`",
        "self_compaction_choice": "`selfCompaction()` returns the choice and the effect together",
        "use_compact_percent": "`updateSettings({ compact_percent })`",
        "self_compaction_default": "the server's configuration file is not an HTTP client's to read or write",
        "use_self_compaction_default": "the same: it writes the server's configuration file",
        "join_sessions": "a callback cannot cross HTTP: `messages()` lists what waits and `relay(id)` answers one",
        "run": "`prompt(...).result` is the same thing, a promise",
        "stream": "an alias of `prompt` in Python",
    },
    "Session": {
        "id": "read with `session.info()`, a property cannot be asynchronous",
        "title": "read with `session.info()`",
        "usage": "read with `session.info()`",
        "locked": "read with `session.info()`",
        "retake": "the server process holds the lock; a program over HTTP never has one to take back",
        "tasks": "the plan is shown by the terminal's panel; no HTTP client has asked for it yet",
        "path": "a path on the server's disk",
        "current": "the server has one current session, so it always is",
        "relay": "`client.relay(id)`, which takes the id of a message `messages()` listed",
        "run": "`prompt(...).result` is the same thing, a promise",
        "resume_stream": "`resume` already returns the run that streams",
        "stream": "an alias of `prompt` in Python",
    },
    "Sessions": {
        "read": "returns the engine's parsed records for a front end that draws the conversation itself; over HTTP "
        "that is `session.history({ full: true })`",
        "read_blocking": "the same, for a thread of the caller's own",
        "install": "switching a conversation in place is `open(id)` over HTTP; the two halves exist so a terminal can "
        "prepare rows between them",
    },
}

#: TypeScript public members with no Python twin, and why.
TYPESCRIPT_ONLY: dict[str, dict[str, str]] = {
    "ZettCodeClient": {
        "baseUrl": "where the server is",
        "health": "the server's liveness",
        "raw": "the transport",
        "settings": "model, effort, permission and harness in one resource; Python reads them as properties",
        "updateSettings": "the same resource, written; `use*` set one field each",
        "addModel": "Python has `zettcode.sdk.add_model`, which edits the configuration file; the server edits its own",
        "updateModel": "Python has `zettcode.sdk.update_model`",
        "removeModel": "Python has `zettcode.sdk.remove_model`",
        "messages": "what other sessions sent and nobody answered yet; Python is handed each by `join_sessions`",
        "runState": "the server's run registry",
        "cancelRun": "the server's run registry; Python closes the stream",
        "approve": "a remote event has no methods; Python answers on the event",
        "answer": "a remote event has no methods; Python answers on the event",
    },
    "Session": {
        "info": "what Python reads as properties",
    },
    "Sessions": {},
}

#: Names a type has in both languages. Only listed names are compared; a type that exists on one side is not an error.
SHARED_TYPES = (
    "Compaction",
    "ContextReport",
    "ContextShare",
    "DayTotals",
    "MentionInfo",
    "Message",
    "ModelCheck",
    "ModelInfo",
    "ModelTotals",
    "ResumeInfo",
    "RunResult",
    "SessionInfo",
    "SessionStatsInfo",
    "SessionTotals",
    "ToolRecord",
    "Totals",
    "Usage",
    "WorkspaceUsage",
)

#: Errors about a Python process; they have no HTTP form.
NOT_OVER_HTTP = {"ClientClosedError", "WorkspaceConflictError", "ZettCodeError"}


def camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part.title() for part in rest)


def snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def python_members(owner: type, extra: tuple[str, ...] = ()) -> set[str]:
    return {name for name, _ in inspect.getmembers(owner) if not name.startswith("_")} | set(extra)


def typescript_members(class_name: str) -> set[str]:
    source = (TS / "client.ts").read_text(encoding="utf-8")
    match = re.search(rf"export class {class_name}\b.*?\n}}\n", source, re.S)
    assert match is not None, f"{class_name} is not in client.ts"
    body = match.group(0)
    names = set(re.findall(r"^  (?:async )?(?:get )?([a-z][A-Za-z0-9]*)\(", body, re.M))
    names |= set(re.findall(r"^  readonly ([a-z][A-Za-z0-9]*)[:=]", body, re.M))
    names.discard("constructor")
    return names


GROUPS = (
    ("Client", sdk_client.Client, ("sessions", "workspace"), "ZettCodeClient"),
    ("Sessions", sdk_client.Sessions, (), "Sessions"),
    ("Session", sdk_session.Session, ("id",), "Session"),
)


@pytest.mark.parametrize(("name", "owner", "extra", "ts_class"), GROUPS, ids=[g[0] for g in GROUPS])
def test_every_python_method_has_the_typescript_name_in_camel_case_or_a_reason_not_to(name, owner, extra, ts_class):
    ts = typescript_members(ts_class)
    missing = sorted(
        member for member in python_members(owner, extra) if camel(member) not in ts and member not in PYTHON_ONLY[name]
    )

    assert missing == [], f"{name}: {missing} have no TypeScript twin; add one, or list the reason in PYTHON_ONLY"


@pytest.mark.parametrize(("name", "owner", "extra", "ts_class"), GROUPS, ids=[g[0] for g in GROUPS])
def test_every_typescript_method_has_the_python_name_or_a_reason_not_to(name, owner, extra, ts_class):
    python = {camel(member) for member in python_members(owner, extra)}
    allowed = TYPESCRIPT_ONLY[ts_class]
    extra_ts = sorted(
        member for member in typescript_members(ts_class) if member not in python and member not in allowed
    )

    assert extra_ts == [], (
        f"{ts_class}: {extra_ts} have no Python twin; rename them, or list the reason in TYPESCRIPT_ONLY"
    )


def test_the_reasons_listed_still_describe_something_that_exists():
    """A difference that was fixed must leave the list, or the list stops meaning anything."""
    stale: list[str] = []
    for name, owner, extra, ts_class in GROUPS:
        python = python_members(owner, extra)
        ts = typescript_members(ts_class)
        stale += [f"PYTHON_ONLY[{name}].{m}" for m in PYTHON_ONLY[name] if m not in python or camel(m) in ts]
        stale += [
            f"TYPESCRIPT_ONLY[{ts_class}].{m}" for m in TYPESCRIPT_ONLY[ts_class] if m not in ts or snake(m) in python
        ]

    assert stale == []


def test_the_client_groups_its_sessions_the_way_python_does():
    ts = typescript_members("ZettCodeClient")

    assert {"sessions", "session"} <= ts


def test_the_wire_name_of_every_event_is_the_snake_case_of_its_python_class():
    skipped = {"AnyEvent", "Event", "RawEvent"}
    serialize = (ROOT / "zettcode/src/zettcode/server/serialize.py").read_text(encoding="utf-8")
    types = (TS / "types.ts").read_text(encoding="utf-8")
    problems: list[str] = []
    for name in sdk_events.__all__:
        if name in skipped:
            continue
        wire = snake(name)
        if f'"type": "{wire}"' not in serialize:
            problems.append(f"{name}: the server never sends type {wire!r}")
        if f'type: "{wire}"' not in types:
            problems.append(f"{name}: the TypeScript RunEvent has no {wire!r}")

    assert problems == []


def test_the_types_both_languages_share_have_one_name():
    types = (TS / "types.ts").read_text(encoding="utf-8")
    problems = [
        name
        for name in SHARED_TYPES
        if not hasattr(sdk_types, name) or not re.search(rf"export (?:interface|type) {name}\b", types)
    ]

    assert problems == []


def test_every_sdk_error_is_one_http_status_and_code_or_has_no_http_form():
    handled = {kind.__name__ for kind, _status, _code in FAILURES}
    unhandled = sorted(set(sdk_errors.__all__) - handled - NOT_OVER_HTTP)

    assert unhandled == [], f"{unhandled} would reach a client as a 500"
