"""The subagent profiles ZettCode exposes through the ``task`` tool.

zett-agent runs a subagent in-process: :class:`SubAgentDefinition` names the
model and the extensions that register the child's tools, and the ``task`` tool
creates one child per call with its own session linked to the caller. ZettCode
supplies its own definitions so a child gets this workspace's tools and this
application's JSONL session store, and so each profile's tool boundary is a
decision made here rather than a zett-agent default.

The profiles are deliberately asymmetric. Exploration cannot write anything;
reasoning has no tools at all; coding may edit files. No profile may run shell:
a child has no channel back to the parent's approval prompt, so a command would
wait forever instead of asking — the parent runs commands itself. No profile
carries a ``task`` tool of its own, so a child cannot delegate to another child.

A child is given the same project instructions the parent has (the workspace's ``AGENTS.md``): one
that edits files and does not know the project's rules is the child most in need of them.

Everything zett-agent contributes is imported inside the two builders rather
than at module scope. The subagent extension imports its SQLite session store,
and that imports SQLAlchemy; a launch that never runs a child must not pay for a
database before the first frame is on screen.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from zettcode.config import DEFAULT_SUBAGENT_MAX_ITERATIONS

from ..storage import SessionStore
from .capabilities import ModelCapabilities

if TYPE_CHECKING:  # pragma: no cover - annotations only; the imports are the cost
    from zett_agent.extensions.base import AgentExtension
    from zett_agent.extensions.subagent import SubAgentDefinition
    from zett_agent.model import AgentModel

#: What every prompt starts from. A child's context is its own: it sees nothing the parent has read or
#: said, and the parent sees nothing it does — only the last message it writes comes back — so each
#: prompt says so, and says what that last message should be.
_ISOLATION = (
    "You work for a parent agent that cannot see anything you read, think or do: the final message you "
    "write is the only thing it receives, so it has to stand on its own. You do not talk to the user."
)

EXPLORE_PROMPT = (
    "You are ZettCode's exploration subagent. "
    + _ISOLATION
    + "\n\nTools: read_file, view_image, glob, grep. You cannot change files or run commands."
    "\n\nHow to work:\n"
    "- Start broad and narrow quickly: glob for the shape of the project, grep for symbols and strings, then "
    "read only the parts that matter (use line ranges for a large file).\n"
    "- Make independent searches in the same step instead of one after another.\n"
    "- Follow a lead until it is confirmed or ruled out. When the question is about every place something "
    "happens, a first match is not an answer.\n"
    "- Trust the files, not memory: report paths and line numbers you actually saw.\n"
    "\nReport the answer first, then the evidence as `path:line - what is there`, then what you could not "
    "determine and where you would look next. As short as the question allows: no preamble, no account of "
    "your search."
)

REASONING_PROMPT = (
    "You are ZettCode's reasoning subagent. "
    + _ISOLATION
    + "\n\nYou have no tools. Reason only from what the task contains, and when something you would need is "
    "not in it, say so instead of assuming it."
    "\n\nHow to work: restate the actual question; list the options, including the boring one; compare them "
    "against the constraints you were given; look for the failure case of the option you prefer; check any "
    "number or claim you rely on."
    "\n\nReport the recommendation first, with the reason in a few sentences; then its risks or costs; then "
    "what is still open and what would settle it. Do not restate the task."
)

CODING_PROMPT = (
    "You are ZettCode's coding subagent. "
    + _ISOLATION
    + "\n\nTools: read_file, view_image, glob, grep, write_file, edit, delete_file. You cannot "
    "run commands, not even tests or a formatter: a command needs the user's approval and you have no way to "
    "ask for it. The parent runs them after it reads your report."
    "\n\nHow to work:\n"
    "- Read before you edit: the file, and enough of its neighbours to match their conventions (naming, "
    "imports, error handling, tests). Follow the project instructions you were given.\n"
    "- Make the smallest change that does what was asked. Do not refactor, rename, reformat or fix what you "
    "were not asked to touch; mention it instead.\n"
    "- Prefer edit with a short, unique old_text to rewriting a whole file, and read the result "
    "back after a change that is not trivial.\n"
    "- When the request is ambiguous, or the code contradicts it, do the part that is clear and say exactly "
    "what you did not do and why. Never guess at a requirement.\n"
    "\nReport what you changed (each path, and the substance of the change), anything you left alone on "
    "purpose, and the exact commands the parent should run to check it."
)

#: What the parent model reads when it decides whether to delegate. A child sees none of the parent's
#: conversation, which is the one thing a parent forgets, so each says what its prompt has to carry.
EXPLORE_DESCRIPTION = (
    "search the workspace read-only (read, glob, grep, images) for a question that needs several searches, and "
    "get back findings with paths and line numbers. It sees none of this conversation: put every name, path "
    "and constraint it needs in the prompt, and say what shape of answer you want."
)
REASONING_DESCRIPTION = (
    "weigh tradeoffs, plans and ambiguous decisions with no tools and no access to the workspace. It can read "
    "nothing: put the facts in the prompt."
)
CODING_DESCRIPTION = (
    "make a bounded change to files in the workspace and report exactly what it changed. It cannot run "
    "commands, so you run the tests and linters after reading its report. It sees none of this conversation: "
    "name the files and the exact change in the prompt."
)


def build_subagents(
    *,
    model: AgentModel,
    persistence: SessionStore,
    capabilities: ModelCapabilities,
    workspace: Path | None = None,
    max_iterations: int = DEFAULT_SUBAGENT_MAX_ITERATIONS,
) -> tuple[SubAgentDefinition, ...]:
    """Return the profiles the ``task`` tool offers, one per tool boundary.

    Args:
        model: Provider the children run on; the caller owns its resources.
        persistence: Session store that writes each child's own log, linked to
            the calling session through ``parent_session_id``.
        capabilities: Parent's capability filter, so a text-only model is not
            offered ``view_image`` inside a child either.
        workspace: Directory whose ``AGENTS.md`` files every child is given, as the parent has
            them; ``None`` gives a child no project instructions.
        max_iterations: Model calls one child may make for one task.
    """
    from zett_agent.extensions.agents_md import AgentsMdExtension
    from zett_agent.extensions.file_system import FileSystemExtension
    from zett_agent.extensions.subagent import SubAgentDefinition
    from zett_agent.extensions.tool_guidelines import ToolGuidelinesExtension
    from zett_agent.model import ReasoningEffort

    def instructions() -> tuple[AgentExtension, ...]:
        """A fresh project-instructions extension per child: it reads the files on every request."""
        return () if workspace is None else (AgentsMdExtension(workspace),)

    return (
        SubAgentDefinition(
            name="explore",
            description=EXPLORE_DESCRIPTION,
            system_prompt=EXPLORE_PROMPT,
            model=model,
            extensions=(
                persistence,
                FileSystemExtension(read_only=True),
                capabilities,
                *instructions(),
                ToolGuidelinesExtension(),
            ),
            reasoning_effort=ReasoningEffort.LOW,
            max_iterations=max_iterations,
        ),
        SubAgentDefinition(
            name="reasoning",
            description=REASONING_DESCRIPTION,
            system_prompt=REASONING_PROMPT,
            model=model,
            extensions=(persistence, capabilities, *instructions(), ToolGuidelinesExtension()),
            reasoning_effort=ReasoningEffort.HIGH,
            max_iterations=max_iterations,
        ),
        SubAgentDefinition(
            name="coding",
            description=CODING_DESCRIPTION,
            system_prompt=CODING_PROMPT,
            model=model,
            extensions=(
                persistence,
                FileSystemExtension(read_only=False),
                capabilities,
                *instructions(),
                ToolGuidelinesExtension(),
            ),
            reasoning_effort=ReasoningEffort.MEDIUM,
            max_iterations=max_iterations,
        ),
    )


def subagent_extension(
    *,
    model: AgentModel,
    persistence: SessionStore,
    capabilities: ModelCapabilities,
    workspace: Path | None = None,
    max_iterations: int = DEFAULT_SUBAGENT_MAX_ITERATIONS,
) -> AgentExtension:
    """Return the ``task`` tool with ZettCode's profiles and their tool boundaries.

    zett-agent's extension supplies the registration and child-session
    machinery; the policy it is configured with is :func:`build_subagents`:
    which profiles exist and what each child may touch.

    Args:
        model: Provider the children run on; the caller owns its resources.
        persistence: Session store that writes each child's own log, linked to
            the calling session through ``parent_session_id``.
        capabilities: Parent's capability filter, so a text-only model is not
            offered ``view_image`` inside a child either.
        workspace: Directory whose ``AGENTS.md`` files every child is given; ``None`` for none.
        max_iterations: Model calls one child may make for one task.
    """
    from zett_agent.extensions.subagent import SubAgentExtension

    return SubAgentExtension(
        build_subagents(
            model=model,
            persistence=persistence,
            capabilities=capabilities,
            workspace=workspace,
            max_iterations=max_iterations,
        )
    )
