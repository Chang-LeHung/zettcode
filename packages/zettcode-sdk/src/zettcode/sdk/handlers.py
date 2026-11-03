"""Answering what the model asks of the program: a shell command to approve, a question to answer.

A run cannot be unattended without a rule for these, because the agent is suspended inside the tool call until
someone answers. The rule is: pass a handler to the run and it answers before the event is yielded; answer the event
yourself while you are iterating; or do neither, and a command is denied and a question declined. Nothing hangs.

A handler may be a plain function or a coroutine function. What it returns decides the answer::

    def only_git(request):
        return request.command.startswith("git ")      # True approves, False denies

    async def ask_a_person(request):
        request.approve(remember=True)                  # answering yourself is fine; return None

``None`` leaves the request unanswered, which means the default (deny, decline) applies once the stream is asked for
its next event. A run started with ``defer_answers=True`` does not apply the default then: it keeps the request open,
so a handler that only shows the request to a person (and returns ``None``) can have it answered later, from a panel,
by the event's own ``approve`` or ``answer``. Whatever is still open when the run ends gets the default.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import TypeAlias

from .events import ApprovalRequested, QuestionAsked

__all__ = [
    "ApprovalHandler",
    "QuestionHandler",
    "approve_all",
    "approve_commands",
    "deny_all",
]

#: Decides one shell command: ``True`` approves, ``False`` denies, ``None`` leaves it to the request's own methods.
ApprovalHandler: TypeAlias = Callable[[ApprovalRequested], "bool | None | Awaitable[bool | None]"]

#: Answers one question: the text answers it, ``None`` leaves it to the request's own methods.
QuestionHandler: TypeAlias = Callable[[QuestionAsked], "str | None | Awaitable[str | None]"]

#: Characters that let a shell run something other than the command that was typed: chaining, pipes,
#: redirection, substitution, grouping and newlines. A command holding one is never matched by a prefix rule.
SHELL_META = frozenset(";&|<>$`\n\r(){}\\")


def approve_all(request: ApprovalRequested) -> bool:
    """Approve every command. Only for a workspace and a model you would trust with a shell."""
    return True


def deny_all(request: ApprovalRequested) -> bool:
    """Deny every command; the model is told and carries on without running anything."""
    return False


def approve_commands(*commands: str) -> ApprovalHandler:
    """Return a handler that approves only the commands named, and denies the rest.

    A command matches when it *is* one of ``commands`` or continues one with arguments (``"git status"`` matches
    ``git status`` and ``git status -s``, not ``git statusx``). It never matches a command holding a character the
    shell treats specially (``;``, ``&``, ``|``, redirection, substitution, newlines), because ``git status; rm -rf
    ~`` starts with ``git status`` too.

    Args:
        commands: The commands to allow, such as ``"git status"``, ``"git diff"``, ``"pytest"``.

    Raises:
        ValueError: A command is blank, or holds a character the shell treats specially.
    """
    allowed: list[str] = []
    for command in commands:
        command = command.strip()
        if not command:
            raise ValueError("A command to allow cannot be blank")
        if SHELL_META & set(command):
            raise ValueError(f"{command!r} holds a shell character; allow the plain command and not a pipeline")
        allowed.append(command)
    rules = tuple(allowed)

    def decide(request: ApprovalRequested) -> bool:
        text = request.command.strip()
        if not text or SHELL_META & set(text):
            return False
        return any(text == rule or text.startswith(rule + " ") for rule in rules)

    return decide


async def apply_approval(request: ApprovalRequested, handler: ApprovalHandler | None) -> None:
    """Let ``handler`` answer ``request``; it stays unanswered when there is none or it declines to say.

    Raises:
        TypeError: The handler returned something other than ``True``, ``False`` or ``None``; a truthy string
            answering "yes" is exactly the mistake that must not approve a shell command.
    """
    if handler is None:
        return
    outcome = handler(request)
    if inspect.isawaitable(outcome):
        outcome = await outcome
    if request.answered or outcome is None:
        return
    if not isinstance(outcome, bool):
        raise TypeError(f"An approval handler returns True, False or None, not {type(outcome).__name__}")
    request.approve() if outcome else request.deny()


async def apply_question(request: QuestionAsked, handler: QuestionHandler | None) -> None:
    """Let ``handler`` answer ``request``; a blank answer or ``None`` leaves it for the default.

    Raises:
        TypeError: The handler returned something other than text or ``None``.
    """
    if handler is None:
        return
    outcome = handler(request)
    if inspect.isawaitable(outcome):
        outcome = await outcome
    if request.answered or outcome is None:
        return
    if not isinstance(outcome, str):
        raise TypeError(f"A question handler returns text or None, not {type(outcome).__name__}")
    if outcome.strip():
        request.answer(outcome)
