"""What the shell approval prompt is allowed to remember.

``zett-agent``'s shell extension asks for approval through an external event,
and can remember a decision only when it is given something to remember it in:
without storage it reports ``remember_supported=False`` and the prompt cannot
offer "always allow this command".

ZettCode keeps that memory in the process, which is what its prompt promises —
the exact command is approved for the rest of this run, and the next start
asks again, exactly like the run-wide policy beside it.
"""

from __future__ import annotations

from zett_agent.extensions.shell_approval import ShellApprovalMode

from .permission import ShellPolicy


class ShellApprovalMemory:
    """Approval memory for one process: a policy per session, exact commands.

    This satisfies ``zett-agent``'s ``ShellApprovalStorage``, which the shell
    extension uses to look up a session's mode and to check and record one
    approved command.

    The shell extension asks :meth:`is_allowed` before it puts a command to the
    reader, which makes it the one place a permission level can say "do not ask":
    ``safe`` answers yes for a command that cannot change anything and ``auto``
    answers yes for every command, while ``ask`` falls through to the commands the
    reader approved by hand. ``deny`` is not decided here, because refusing is not
    a thing this question can express.
    """

    def __init__(self, policy: ShellPolicy | None = None) -> None:
        """Start with no session policy and nothing approved.

        Args:
            policy: The permission level to consult; without one every command
                is put to the reader, which is what ``ask`` does.
        """
        self._modes: dict[str, ShellApprovalMode] = {}
        self._allowed: set[str] = set()
        self._policy = policy

    async def get_session_mode(self, session_id: str) -> ShellApprovalMode:
        """Return a session's policy, which is review until one is set."""
        return self._modes.get(session_id, ShellApprovalMode.REVIEW)

    async def set_session_mode(self, session_id: str, mode: ShellApprovalMode) -> None:
        """Record one session's policy for the rest of the process."""
        self._modes[session_id] = mode

    async def clear_session_mode(self, session_id: str) -> None:
        """Forget a session's policy, so the next prompt reviews again."""
        self._modes.pop(session_id, None)

    async def is_allowed(self, session_id: str, command: str) -> bool:
        """Return whether a command may run without asking: by level, or approved by hand."""
        if self._policy is not None and self._policy.allows_unasked(command):
            return True
        return command in self._allowed

    async def allow_command(self, command: str) -> None:
        """Remember one exact command for the rest of this run."""
        self._allowed.add(command)
