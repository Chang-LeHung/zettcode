"""How much of the shell the agent may use without asking, and what enforces it.

Four levels, from the strictest to the loosest, and they are one setting rather
than four features because the thing they decide is one question — *when a shell
command arrives, who answers?*

=======  ===============================================================
``deny``   Nobody runs it: the command fails and the model is told why.
``ask``    The reader answers each one (the default, and what the prompt does).
``safe``   Commands that provably cannot change anything run; the rest ask.
``auto``   Every command runs.
=======  ===============================================================

The level is shared state between the shell, which changes it, and two things on
the agent's side that read it on every shell call: the approval memory, which is
what lets ``safe`` and ``auto`` skip the prompt, and :class:`ShellDenyExtension`,
which is what makes ``deny`` refuse. Neither keeps its own copy, so a change takes
effect on the next command, including one the model is about to issue in the
request that is running now.

Only the shell is governed. The file tools, the MCP tools, and the web tools are
not behind a prompt in this application and this setting does not put them behind
one: the level is named for what it controls, and the picker says so.
"""

from __future__ import annotations

from pathlib import Path

from zett_agent.agent import AgentRunContext
from zett_agent.extensions.base import AgentExtension, ToolCallNext
from zett_agent.extensions.shell_approval import SHELL_APPROVAL_TOOL_NAME, ShellApprovalMode
from zett_agent.messages import ToolCall
from zett_agent.tools.base import ToolResult

from zettcode._compat import StrEnum

from .readonly import is_read_only


class Permission(StrEnum):
    """How much of the shell may run without a person answering for it.

    Attributes:
        DENY: No shell command runs; the model is told, and can carry on without.
        ASK: Every command that is not already approved is put to the reader.
        SAFE: Commands recognised as unable to change anything run unasked.
        AUTO: Every command runs unasked.
    """

    DENY = "deny"
    ASK = "ask"
    SAFE = "safe"
    AUTO = "auto"


#: The levels strictest first, which is the order the picker lists them in.
PERMISSION_LEVELS: tuple[Permission, ...] = (Permission.DENY, Permission.ASK, Permission.SAFE, Permission.AUTO)

#: A shell command refused by ``deny``, as the model reads it. It says what the
#: reader did and what is still open to the model, because a bare "refused" sends
#: a model looking for a way around it.
DENIED_MESSAGE = (
    "Shell commands are turned off by the user (permission: deny). "
    "Use the file tools to read and edit, or tell the user what command you need."
)


def parse_permission(name: str) -> Permission:
    """Return the level a user typed, or raise with the names that are valid.

    Args:
        name: A level's name; case and surrounding space do not matter.

    Raises:
        ValueError: The name is not one of the four, and the message lists them.
    """
    try:
        return Permission(name.strip().lower())
    except ValueError:
        levels = ", ".join(level.value for level in PERMISSION_LEVELS)
        raise ValueError(f"Unknown permission: {name}. Try one of: {levels}") from None


class ShellPolicy:
    """The level in force, and the question each level asks of a command.

    One instance is shared by the shell, the approval memory, and the deny
    extension. It holds a single enum member, which is read and replaced
    atomically, so the shell thread changing it and the agent's loop reading it
    need no lock: a command in flight sees the old level or the new one, never a
    mixture.
    """

    def __init__(self, level: Permission = Permission.ASK, workspace: Path | None = None) -> None:
        """Start at a level, for commands that run in a workspace.

        Args:
            level: The level in force until it is changed.
            workspace: Directory commands run in; ``git`` is only ever judged
                read-only against a repository that can be found from here.
        """
        self.level = level
        self.workspace = workspace

    @classmethod
    def from_mode(cls, mode: ShellApprovalMode, workspace: Path | None = None) -> ShellPolicy:
        """Start at the level the configured approval mode stands for."""
        return cls(Permission.AUTO if mode is ShellApprovalMode.ALLOW_ALL else Permission.ASK, workspace)

    def allows_unasked(self, command: str) -> bool:
        """Return whether this level lets a command run without putting it to the reader.

        ``deny`` never reaches here — the deny extension has already refused —
        but it answers no all the same, so a caller that asks cannot be told yes
        by mistake.
        """
        if self.level is Permission.AUTO:
            return True
        if self.level is Permission.SAFE:
            return is_read_only(command, self.workspace)
        return False


class ShellDenyExtension(AgentExtension):
    """Refuse every shell command while the level is ``deny``.

    The approval extension can say yes or ask but has no way to say no on the
    reader's behalf, and answering "abort" to a prompt that was never shown would
    mean putting the panel up and tearing it down. So this runs before it, as the
    outer layer of the onion, and raises into ordinary tool-failure handling: the
    model sees a failed ``bash`` call whose message says why.
    """

    #: Before the approval extension, which is the layer that would otherwise put
    #: the command to the reader.
    priority = 50

    def __init__(self, policy: ShellPolicy) -> None:
        """Read the level from the policy the shell changes."""
        self._policy = policy

    async def on_tool_call(self, context: AgentRunContext, call: ToolCall, call_next: ToolCallNext) -> ToolResult:
        """Let every tool through except a shell command, which ``deny`` refuses."""
        if self._policy.level is Permission.DENY and call.name == SHELL_APPROVAL_TOOL_NAME:
            raise PermissionError(DENIED_MESSAGE)
        return await call_next()
