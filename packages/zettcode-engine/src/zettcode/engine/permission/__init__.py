"""How much of the shell the agent may use without asking, and what enforces it.

Four levels, from the strictest to the loosest, and they are one setting rather
than four features because the thing they decide is one question — *when a shell
command arrives, who answers?*

=======  ===============================================================
``deny``   Nobody runs it: the command fails and the model is told why.
``ask``    The reader answers each one (the default, and what the prompt does).
``safe``   Every command runs, inside an operating-system sandbox that lets it
           write the workspace and ``/tmp`` only (:mod:`.sandbox`). Where the
           machine has no sandbox: read-only commands run and the rest ask.
``full``   Every command runs with the user's own access. (Formerly ``auto``.)
=======  ===============================================================

The level is shared state between the shell, which changes it, and two things on
the agent's side that read it on every shell call: the approval memory, which is
what lets ``safe`` and ``full`` skip the prompt, and :class:`ShellDenyExtension`,
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
from zett_agent.sandbox.base import Sandbox
from zett_agent.tools.base import ToolResult

from zettcode._compat import StrEnum

from ..tools.boundary import Boundary, Sandboxer
from .readonly import is_read_only
from .sandbox import ShellSandbox


class Permission(StrEnum):
    """How much of the shell may run without a person answering for it.

    Attributes:
        DENY: No shell command runs; the model is told, and can carry on without.
        ASK: Every command that is not already approved is put to the reader.
        SAFE: Every command runs unasked, in a sandbox that writes only the workspace and the temporary
            directory. On a machine with no sandbox: only commands that cannot change anything run unasked.
        FULL: Every command runs unasked with the user's own access.
        AUTO: The old name of ``FULL``, kept so code and config written before the rename still work.
    """

    DENY = "deny"
    ASK = "ask"
    SAFE = "safe"
    FULL = "full"
    AUTO = "full"


#: The levels strictest first, which is the order the picker lists them in.
PERMISSION_LEVELS: tuple[Permission, ...] = (Permission.DENY, Permission.ASK, Permission.SAFE, Permission.FULL)

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
        name: A level's name; case and surrounding space do not matter. ``auto``, the name ``full`` had before
            it was renamed, is still taken.

    Raises:
        ValueError: The name is not one of the four, and the message lists them.
    """
    wanted = name.strip().lower()
    try:
        return Permission("full" if wanted == "auto" else wanted)
    except ValueError:
        levels = ", ".join(level.value for level in PERMISSION_LEVELS)
        raise ValueError(f"Unknown permission: {name}. Try one of: {levels}") from None


class ShellPolicy(Boundary):
    """The level in force, and the question each level asks of a command.

    One instance is shared by the shell, the approval memory, and the deny
    extension. It holds a single enum member, which is read and replaced
    atomically, so the shell thread changing it and the agent's loop reading it
    need no lock: a command in flight sees the old level or the new one, never a
    mixture.
    """

    def __init__(
        self,
        level: Permission = Permission.ASK,
        workspace: Path | None = None,
        sandbox: ShellSandbox | None = None,
    ) -> None:
        """Start at a level, for commands that run in a workspace.

        Args:
            level: The level in force until it is changed.
            workspace: Directory commands run in; ``git`` is only ever judged
                read-only against a repository that can be found from here.
            sandbox: What ``safe`` runs commands in. ``None`` builds the default for ``workspace`` (no network),
                and with no workspace there is no sandbox at all.
        """
        self.level = level
        self.workspace = workspace
        self.sandbox = sandbox if sandbox is not None else (ShellSandbox(workspace) if workspace else None)

    @property
    def sandboxed(self) -> bool:
        """Return whether a command is run inside the sandbox right now: level ``safe`` on a machine that has one."""
        return self.sandbox_now() is not None

    def sandbox_now(self) -> Sandboxer | None:
        """Return the sandbox the next command runs in, or ``None`` when it runs as given."""
        if self.level is Permission.SAFE and self.sandbox is not None and self.sandbox.available:
            return self.sandbox
        return None

    def jit_sandbox(self) -> Sandbox | None:
        """Return the boundary code the model writes runs in, or ``None`` when it gets the user's own access.

        One answer for one decision: the just-in-time harness asks this instead of reading the level itself, so
        the shell and the code the model wrote cannot disagree about what a level means. `full` is the level that
        grants the model the reader's access, so nothing is left for a boundary to hold back; every other level
        bounds it with the boundary `safe` uses, and a machine with no sandbox has nothing to pass on — the
        reader is told, at the level that claimed a boundary (see :meth:`sandbox_missing`).
        """
        if self.level is Permission.FULL:
            return None
        return self.sandbox.boundary if self.sandbox is not None else None

    def sandbox_missing(self) -> bool:
        """Return whether the level in force promises a boundary this machine does not have."""
        return self.level is not Permission.FULL and not (self.sandbox is not None and self.sandbox.available)

    @classmethod
    def from_mode(
        cls, mode: ShellApprovalMode, workspace: Path | None = None, sandbox: ShellSandbox | None = None
    ) -> ShellPolicy:
        """Start at the level the configured approval mode stands for."""
        return cls(Permission.FULL if mode is ShellApprovalMode.ALLOW_ALL else Permission.ASK, workspace, sandbox)

    def allows_unasked(self, command: str) -> bool:
        """Return whether this level lets a command run without putting it to the reader.

        ``deny`` never reaches here — the deny extension has already refused —
        but it answers no all the same, so a caller that asks cannot be told yes
        by mistake.
        """
        if self.level is Permission.FULL:
            return True
        if self.level is Permission.SAFE:
            # The sandbox is the boundary, so any command may run in it. Without one, only a command that
            # provably changes nothing is trusted.
            return self.sandboxed or is_read_only(command, self.workspace)
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
