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
"""

from __future__ import annotations

from zett_agent.extensions.file_system import FileSystemExtension
from zett_agent.extensions.subagent import SubAgentDefinition, SubAgentExtension
from zett_agent.extensions.tool_guidelines import ToolGuidelinesExtension
from zett_agent.model import AgentModel, ReasoningEffort

from .capabilities import ModelCapabilities
from .storage import SessionStore

EXPLORE_PROMPT = (
    "You are ZettCode's exploration subagent. Inspect the workspace with the read-only tools "
    "(read_file, view_image, glob, grep) and return concise findings: the relevant paths, symbols, "
    "and the uncertainties you could not resolve. You cannot change files or run commands, and you "
    "do not talk to the user directly."
)

REASONING_PROMPT = (
    "You are ZettCode's reasoning subagent. Work the delegated problem through independently: check "
    "assumptions, compare alternatives, and return a short report with a recommendation, the risks, "
    "and the questions still open. You have no tools; reason from the context you are given."
)

CODING_PROMPT = (
    "You are ZettCode's coding subagent. Make the requested change in the workspace with the "
    "filesystem tools, then report exactly what you changed and what still needs running. You cannot "
    "run commands; the parent agent does that after reading your report."
)


def build_subagents(
    *,
    model: AgentModel,
    persistence: SessionStore,
    capabilities: ModelCapabilities,
) -> tuple[SubAgentDefinition, ...]:
    """Return the profiles the ``task`` tool offers, one per tool boundary.

    Args:
        model: Provider the children run on; the caller owns its resources.
        persistence: Session store that writes each child's own log, linked to
            the calling session through ``parent_session_id``.
        capabilities: Parent's capability filter, so a text-only model is not
            offered ``view_image`` inside a child either.
    """
    return (
        SubAgentDefinition(
            name="explore",
            description="search the workspace read-only and return evidence with paths.",
            system_prompt=EXPLORE_PROMPT,
            model=model,
            extensions=(
                persistence,
                FileSystemExtension(read_only=True),
                capabilities,
                ToolGuidelinesExtension(),
            ),
            reasoning_effort=ReasoningEffort.LOW,
        ),
        SubAgentDefinition(
            name="reasoning",
            description="analyze tradeoffs and plans without touching the workspace.",
            system_prompt=REASONING_PROMPT,
            model=model,
            extensions=(persistence, capabilities, ToolGuidelinesExtension()),
            reasoning_effort=ReasoningEffort.HIGH,
        ),
        SubAgentDefinition(
            name="coding",
            description="edit the workspace and report exactly what it changed.",
            system_prompt=CODING_PROMPT,
            model=model,
            extensions=(
                persistence,
                FileSystemExtension(read_only=False),
                capabilities,
                ToolGuidelinesExtension(),
            ),
            reasoning_effort=ReasoningEffort.MEDIUM,
            max_iterations=36,
        ),
    )


class ZettCodeSubAgents(SubAgentExtension):
    """The ``task`` tool with ZettCode's profiles and their tool boundaries.

    Inherits the registration and child-session machinery from zett-agent; what
    this class owns is :func:`build_subagents`, which is the whole policy: which
    profiles exist and what each child may touch.
    """

    def __init__(
        self,
        *,
        model: AgentModel,
        persistence: SessionStore,
        capabilities: ModelCapabilities,
    ) -> None:
        """Configure the task tool with this application's subagent profiles."""
        super().__init__(
            build_subagents(
                model=model,
                persistence=persistence,
                capabilities=capabilities,
            )
        )
