"""The subagent profiles ZettCode exposes through the ``task`` tool.

zett-agent runs a subagent in-process: :class:`SubAgentDefinition` names the
model and the extensions that register the child's tools, and the ``task`` tool
creates one child per call with its own session linked to the caller. ZettCode
supplies its own definitions so a child gets this workspace's tools and this
application's JSONL session store, and so each profile's tool boundary is a
decision made here rather than a zett-agent default.

The profiles are deliberately asymmetric. Exploration cannot write anything;
reasoning has no tools at all; coding may edit files, and when the parent has a shell it has the parent's own
tools, the shell included, under the parent's permission level (a command that needs approval is put to the
person through the parent, see :mod:`.relay`). No profile carries a ``task`` tool of its own, so a child cannot
delegate to another child.

A child is given the same project instructions the parent has (the workspace's ``AGENTS.md``): one
that edits files and does not know the project's rules is the child most in need of them.

Everything zett-agent contributes is imported inside the builders rather
than at module scope. The subagent extension imports its SQLite session store,
and that imports SQLAlchemy; a launch that never runs a child must not pay for a
database before the first frame is on screen.

A child runs on the model the *parent's request* runs on, not the one the runtime was built with: ``/model``
and resuming a session change the parent's model, and a profile that kept the build-time adapter would
quietly answer on another provider. Its reasoning effort is the profile's default unless the parent model
asks for another through the ``task`` tool's ``reasoning_effort``; either way it is moved to the nearest
level the model takes, because an endpoint that rejects a level it does not know fails the whole task.
"""

from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar
from copy import deepcopy
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from zettcode.config import DEFAULT_SUBAGENT_MAX_ITERATIONS

from ..storage import SessionStore
from .capabilities import ModelCapabilities

if TYPE_CHECKING:  # pragma: no cover - annotations only; the imports are the cost
    from zett_agent.agent import Agent, AgentRunContext
    from zett_agent.extensions.base import AgentExtension
    from zett_agent.extensions.subagent import SubAgentDefinition, SubAgentExtension
    from zett_agent.model import AgentModel
    from zett_agent.tools.base import AgentTool

#: The effort the parent model asked for on the ``task`` call being run. A tool call is one task, so this
#: is per call even when several run in parallel; ``None`` outside one, or when it asked for nothing.
_REQUESTED_EFFORT: ContextVar[str | None] = ContextVar("zettcode_subagent_effort", default=None)

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
    + "\n\nTools: read, glob, grep. You cannot change files or run commands."
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
    "You are ZettCode's coding subagent. " + _ISOLATION + "\n\nTools: read, glob, grep, write_file, edit. You cannot "
    "run commands, not even tests or a formatter: a command needs the user's approval and you have no way to "
    "ask for it. It also has no file-deletion tool: deleting is a command too. The parent runs them after it "
    "reads your report."
    "\n\nHow to work:\n"
    "- Read before you edit: the file, and enough of its neighbours to match their conventions (naming, "
    "imports, error handling, tests). Follow the project instructions you were given.\n"
    "- Make the smallest change that does what was asked. Do not refactor, rename, reformat or fix what you "
    "were not asked to touch; mention it instead.\n"
    "- Prefer edit with a short, unique old_string to rewriting a whole file, and read the result "
    "back after a change that is not trivial.\n"
    "- When the request is ambiguous, or the code contradicts it, do the part that is clear and say exactly "
    "what you did not do and why. Never guess at a requirement.\n"
    "\nReport what you changed (each path, and the substance of the change), anything you left alone on "
    "purpose, and the exact commands the parent should run to check it."
)

#: The coding child of an agent that has a shell: it is given the parent's own tools and permission level.
CODING_SHELL_PROMPT = (
    "You are ZettCode's coding subagent. "
    + _ISOLATION
    + "\n\nTools: read, write_file, edit and bash, and whatever else the user has set up for the parent (skills, "
    "MCP servers). You cannot start another subagent, and you cannot put a question to the user: what you need to "
    "know has to be in the task, and anything else is for the parent to ask."
    "\n\nbash runs under the user's permission level, exactly as it does for the parent: a command that level "
    "does not allow unasked is put to the user for approval, and at `deny` it is refused. Search with rg, grep "
    "and find, and read a file with read (in line ranges for a long one) rather than with cat, sed or head. "
    "There is no file-deletion tool: remove a file with rm, which follows the same rule."
    "\n\nHow to work:\n"
    "- Read before you edit: the file, and enough of its neighbours to match their conventions (naming, "
    "imports, error handling, tests). Follow the project instructions you were given.\n"
    "- Make the smallest change that does what was asked. Do not refactor, rename, reformat or fix what you "
    "were not asked to touch; mention it instead.\n"
    "- Prefer edit with a short, unique old_string to rewriting a whole file, and read the result "
    "back after a change that is not trivial.\n"
    "- Run the tests or the formatter when the task calls for it, and report what they printed. When a command "
    "was refused or declined, say so instead of guessing at its result.\n"
    "- When the request is ambiguous, or the code contradicts it, do the part that is clear and say exactly "
    "what you did not do and why. Never guess at a requirement.\n"
    "\nReport what you changed (each path, and the substance of the change), anything you left alone on "
    "purpose, what you ran and what it showed, and any command you could not run."
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
CODING_SHELL_DESCRIPTION = (
    "make a bounded change to files in the workspace, run what the change needs (tests, a formatter), and "
    "report exactly what it changed and what it ran. It works under the user's permission level as you do, so "
    "a command may be put to the user for approval. It sees none of this conversation: name the files and the "
    "exact change in the prompt."
)

#: The profiles that are given the parent's own extensions (its tools and its permission level), and not only
#: what a profile lists. The others are deliberately small: one only reads, one has no tools at all.
INHERITING = frozenset({"coding"})


def build_subagents(
    *,
    model: AgentModel,
    persistence: SessionStore,
    capabilities: ModelCapabilities,
    workspace: Path | None = None,
    max_iterations: int = DEFAULT_SUBAGENT_MAX_ITERATIONS,
    shell: bool = False,
) -> tuple[SubAgentDefinition, ...]:
    """Return the profiles the ``task`` tool offers, one per tool boundary.

    Args:
        model: Provider the children run on; the caller owns its resources.
        persistence: Session store that writes each child's own log, linked to
            the calling session through ``parent_session_id``.
        capabilities: Parent's capability filter, so a text-only model is given the text reader inside a child
            too.
        workspace: Directory whose ``AGENTS.md`` files every child is given, as the parent has
            them; ``None`` gives a child no project instructions.
        max_iterations: Model calls one child may make for one task.
        shell: Whether the ``coding`` child is given the parent's own tools, shell included, when it is created
            (see :data:`INHERITING`). Without it the child edits files and nothing else, and says so in its prompt.
    """
    from zett_agent.extensions.agents_md import AgentsMdExtension
    from zett_agent.extensions.subagent import SubAgentDefinition
    from zett_agent.model import ReasoningEffort

    from .files import FileTools
    from .guidance import tool_guidance

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
                FileTools(read_only=True),
                capabilities,
                *instructions(),
                tool_guidance(),
            ),
            reasoning_effort=ReasoningEffort.LOW,
            max_iterations=max_iterations,
        ),
        SubAgentDefinition(
            name="reasoning",
            description=REASONING_DESCRIPTION,
            system_prompt=REASONING_PROMPT,
            model=model,
            extensions=(persistence, capabilities, *instructions(), tool_guidance()),
            reasoning_effort=ReasoningEffort.HIGH,
            max_iterations=max_iterations,
        ),
        SubAgentDefinition(
            name="coding",
            description=CODING_SHELL_DESCRIPTION if shell else CODING_DESCRIPTION,
            system_prompt=CODING_SHELL_PROMPT if shell else CODING_PROMPT,
            model=model,
            extensions=(
                persistence,
                # With a shell the file tools come from the parent's own bundle, which has the shell in it.
                *(() if shell else (FileTools(read_only=False),)),
                capabilities,
                *instructions(),
                tool_guidance(),
            ),
            reasoning_effort=ReasoningEffort.MEDIUM,
            max_iterations=max_iterations,
        ),
    )


@cache
def _extension_class() -> Callable[..., SubAgentExtension]:
    """Return the ``task`` extension that runs a child on its parent's model and lets the parent pick the effort.

    Built on first use for the reason the rest of this module imports late: the framework's module is
    what pulls in the database layer.
    """
    from zett_agent.agent import AgentRunConfig
    from zett_agent.extensions.subagent import SubAgentExtension
    from zett_agent.model import ReasoningEffort
    from zett_agent.tools.base import AgentTool as Tool

    from .relay import RelayingAgent, relay_to

    class ParentModelSubAgents(SubAgentExtension):
        """The framework's ``task`` tool, with the child on the parent's model and an optional effort."""

        def __init__(
            self,
            subagents: Any,
            *,
            capabilities: ModelCapabilities,
            shares: Callable[[AgentExtension], bool] | None = None,
        ) -> None:
            super().__init__(subagents)
            self._capabilities = capabilities
            self._shares = shares

        def _levels(self, context: AgentRunContext) -> tuple[ReasoningEffort, ...]:
            """Return the levels the parent's model takes: every one for a model the runtime has no entry for."""
            config = self._capabilities.config_of(context.model)
            return config.efforts if config is not None else tuple(ReasoningEffort)

        def _inherited(self, definition: SubAgentDefinition, context: AgentRunContext) -> tuple[AgentExtension, ...]:
            """Return the parent's own extensions that a child of this profile is given as well.

            The parent's extension instances are shared, not copied: they are written to serve several sessions at
            once, and sharing is what puts the child under the same permission level, the same approval memory and
            the same skills and servers as the parent.
            """
            if self._shares is None or definition.name not in INHERITING:
                return ()
            return tuple(extension for extension in context.extensions if self._shares(extension))

        async def _create_child(
            self, definition: SubAgentDefinition, child_session_id: str, context: AgentRunContext
        ) -> Agent:
            """Create the child on the model of the request that delegated, at a level that model takes."""
            parent = context.model or definition.model
            asked = _REQUESTED_EFFORT.get()
            effort = ReasoningEffort(asked) if asked else definition.reasoning_effort
            config = self._capabilities.config_of(parent)
            if config is not None:
                effort = config.accepted_effort(effort)
            child = await RelayingAgent.create(
                parent,
                config=AgentRunConfig(session_id=child_session_id, parent_session_id=context.session_id),
                system_prompt=definition.system_prompt,
                tools=definition.tools,
                extensions=(*definition.extensions, *self._inherited(definition, context)),
                reasoning_effort=effort,
                max_iterations=definition.max_iterations,
            )
            child.relay = relay_to(context)
            return child

        def _build_tool(self, context: AgentRunContext, subagents: Any) -> AgentTool:
            """Add an optional ``reasoning_effort`` to the framework's tool, listing what this model takes."""
            base = super()._build_tool(context, subagents)
            levels = self._levels(context)
            names = [level.value for level in levels]
            parameters = deepcopy(base.parameters)
            parameters["properties"]["reasoning_effort"] = {
                "type": "string",
                "enum": names,
                "description": (
                    "How hard the subagent thinks. Leave it out for the profile's default "
                    "(explore low, coding medium, reasoning high)."
                ),
            }
            inner = base.handler

            async def handler(**arguments: Any) -> Any:
                asked = arguments.pop("reasoning_effort", None)
                if asked is not None and asked not in names:
                    raise ValueError(f"Unknown reasoning_effort {asked!r}; this model takes: {', '.join(names)}")
                token = _REQUESTED_EFFORT.set(asked)
                try:
                    return await inner(**arguments)
                finally:
                    _REQUESTED_EFFORT.reset(token)

            return Tool(
                name=base.name,
                description=base.description,
                parameters=parameters,
                handler=handler,
                guidelines=(
                    *base.guidelines,
                    f"Set reasoning_effort only when a task is harder or easier than its profile assumes; "
                    f"the levels you can ask for are {', '.join(names)}.",
                ),
                snippet=base.snippet,
                execution_mode=base.execution_mode,
            )

    return ParentModelSubAgents


def subagent_extension(
    *,
    model: AgentModel,
    persistence: SessionStore,
    capabilities: ModelCapabilities,
    workspace: Path | None = None,
    max_iterations: int = DEFAULT_SUBAGENT_MAX_ITERATIONS,
    shares: Callable[[AgentExtension], bool] | None = None,
) -> AgentExtension:
    """Return the ``task`` tool with ZettCode's profiles and their tool boundaries.

    zett-agent's extension supplies the registration and child-session
    machinery; the policy it is configured with is :func:`build_subagents`:
    which profiles exist and what each child may touch.

    Args:
        model: Provider a child runs on when the request that delegated names none; otherwise the
            children use the parent request's own.
        persistence: Session store that writes each child's own log, linked to
            the calling session through ``parent_session_id``.
        capabilities: Parent's capability filter, so a text-only model is given the text reader inside a child
            too, and the lookup of which levels a model takes.
        workspace: Directory whose ``AGENTS.md`` files every child is given; ``None`` for none.
        max_iterations: Model calls one child may make for one task.
        shares: Says, of each extension the parent runs, whether the ``coding`` child is given it too. That is what
            gives the child the parent's tools and puts its shell under the parent's permission level; the caller,
            which knows what every extension is, decides (the ``task`` tool itself and the harness are not shared).
            ``None`` shares nothing, and the child then edits files and has no shell.
    """
    return _extension_class()(
        build_subagents(
            model=model,
            persistence=persistence,
            capabilities=capabilities,
            workspace=workspace,
            max_iterations=max_iterations,
            shell=shares is not None,
        ),
        capabilities=capabilities,
        shares=shares,
    )
