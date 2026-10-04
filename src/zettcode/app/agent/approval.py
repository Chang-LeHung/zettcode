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


class ShellApprovalMemory:
    """Approval memory for one process: a policy per session, exact commands.

    This satisfies ``zett-agent``'s ``ShellApprovalStorage``, which the shell
    extension uses to look up a session's mode and to check and record one
    approved command.
    """

    def __init__(self) -> None:
        """Start with no session policy and nothing approved."""
        self._modes: dict[str, ShellApprovalMode] = {}
        self._allowed: set[str] = set()

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
        """Return whether this run already approved one exact command."""
        return command in self._allowed

    async def allow_command(self, command: str) -> None:
        """Remember one exact command for the rest of this run."""
        self._allowed.add(command)
