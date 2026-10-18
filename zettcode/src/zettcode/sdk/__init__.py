"""The ZettCode SDK: the coding agent, driven from code.

Everything the terminal application does with the agent is available here without a terminal: send a prompt and read
the result, stream the events of a run, answer shell approvals and questions the model asks, switch model, reasoning
effort and permission level, keep several conversations, resume an interrupted request, compact, measure the
context, export, and read the history. It runs the same agent, tools, plugins, MCP servers, skills, project
instructions and session store as the terminal.

One prompt, no ceremony::

    import zettcode.sdk as zc

    result = await zc.prompt("summarize the README", workspace=".", permission="deny")
    print(result.text)

A conversation, with progress and a rule for shell commands::

    async with zc.Client(".", permission="safe") as client:
        async with client.prompt("make the tests pass", on_approval=zc.approve_commands("pytest")) as run:
            async for event in run:
                match event:
                    case zc.TextDelta(text=text):
                        print(text, end="")
                    case zc.ToolStarted(name=name):
                        print(f"\\n[{name}]")
        print(run.result.usage.total_tokens, "tokens")
        followup = await client.prompt("and explain what you changed")     # awaiting it gives the result

Importing this package costs nothing: the names below load their module the first time they are used, and the
agent itself is loaded when a :class:`Client` is made. Only what a program reaches for every day is listed here; the
rest is in the submodules, which are just as light to import:

* :mod:`zettcode.sdk.events` — the other events (``Steered``, ``ModelStopped``, ``Notice``, ``UsageUpdated``,
  ``CompactionStarted``/``CompactionFinished``, ``RawEvent``) and ``AnyEvent`` for annotations.
* :mod:`zettcode.sdk.types` — ``ModelInfo``, ``SessionInfo``, ``Message``, ``ToolRecord``, ``ContextReport``,
  ``Compaction``, ``ResumeInfo`` and the other values the methods return.
* :mod:`zettcode.sdk.errors` — every error; they all derive from :class:`ZettCodeError`.
* :mod:`zettcode.sdk.handlers` — ``ApprovalHandler``/``QuestionHandler`` for annotations.

Nothing here starts a terminal, joins the broker that lets terminal sessions message each other, or checks for a
release.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - for type checkers and editors; at runtime the names load on first use
    from .client import Client, prompt, prompt_sync
    from .errors import ConfigurationError, RunError, ZettCodeError
    from .events import (
        ApprovalRequested,
        Finished,
        QuestionAsked,
        ReasoningDelta,
        TextDelta,
        ToolFinished,
        ToolStarted,
    )
    from .handlers import approve_all, approve_commands, deny_all
    from .models import add_model, list_models, remove_model, update_model
    from .session import RunStream, Session
    from .types import (
        DayTotals,
        Image,
        MentionInfo,
        ModelCheck,
        ModelTotals,
        RunResult,
        SessionStatsInfo,
        SessionTotals,
        Totals,
        Usage,
        WorkspaceUsage,
    )

#: Where each public name lives. The package resolves a name by importing only that module.
_EXPORTS: dict[str, str] = {
    "Client": ".client",
    "prompt": ".client",
    "prompt_sync": ".client",
    "Session": ".session",
    "RunStream": ".session",
    "RunResult": ".types",
    "Usage": ".types",
    "Image": ".types",
    "MentionInfo": ".types",
    "DayTotals": ".types",
    "ModelCheck": ".types",
    "ModelTotals": ".types",
    "SessionStatsInfo": ".types",
    "SessionTotals": ".types",
    "Totals": ".types",
    "WorkspaceUsage": ".types",
    "TextDelta": ".events",
    "ReasoningDelta": ".events",
    "ToolStarted": ".events",
    "ToolFinished": ".events",
    "ApprovalRequested": ".events",
    "QuestionAsked": ".events",
    "Finished": ".events",
    "approve_all": ".handlers",
    "approve_commands": ".handlers",
    "deny_all": ".handlers",
    "ZettCodeError": ".errors",
    "ConfigurationError": ".errors",
    "RunError": ".errors",
    "add_model": ".models",
    "list_models": ".models",
    "remove_model": ".models",
    "update_model": ".models",
}

#: Kept literal so linters and editors can read it; a test checks it names exactly the keys of ``_EXPORTS``.
__all__ = [
    "ApprovalRequested",
    "Client",
    "ConfigurationError",
    "DayTotals",
    "Finished",
    "Image",
    "MentionInfo",
    "ModelCheck",
    "ModelTotals",
    "QuestionAsked",
    "ReasoningDelta",
    "RunError",
    "RunResult",
    "RunStream",
    "Session",
    "SessionStatsInfo",
    "SessionTotals",
    "TextDelta",
    "ToolFinished",
    "ToolStarted",
    "Totals",
    "Usage",
    "WorkspaceUsage",
    "ZettCodeError",
    "add_model",
    "approve_all",
    "approve_commands",
    "deny_all",
    "list_models",
    "prompt",
    "prompt_sync",
    "remove_model",
    "update_model",
]


def __getattr__(name: str) -> Any:
    """Load a public name's module on first use, and keep the name so the lookup happens once."""
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module, __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """List the public names, so completion shows them without loading anything."""
    return sorted({*globals(), *_EXPORTS})
