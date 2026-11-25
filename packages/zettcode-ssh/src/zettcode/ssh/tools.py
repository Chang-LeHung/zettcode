"""Remote tools built through zett-agent's typed decorator, named apart from the local ones.

The local coding tools keep their names and keep working; these add the same operations on the SSH host that
``/ssh`` selected. The ``ssh__`` prefix is the runtime's own namespacing for a tool that belongs to a server, so a
row reads "ssh/read" in the transcript and the model can never mistake one for the other.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from pydantic import Field
from zett_agent.tools.base import AgentTool, ToolExecutionMode, tool

#: The same boundaries the local tools use. The main agent reads, writes and runs a shell — searching is the shell's
#: job, so there is no remote glob/grep there either; an explore subagent has no shell and gets read/glob/grep.
#: ``read_file`` is not a tool of its own: it replaces ``read`` for a model that cannot take a picture.
READING = frozenset({"read", "glob", "grep"})
ALL = frozenset({"read", "write_file", "edit", "bash"})
PREFIX = "ssh__"
FilePath = Annotated[str, Field(min_length=1)]
Offset = Annotated[int, Field(ge=1)]
Limit = Annotated[int, Field(ge=1, le=2000)]
MaxResults = Annotated[int, Field(ge=1, le=5000)]
Timeout = Annotated[float, Field(gt=0, le=120)]


def tool_name(operation: str) -> str:
    """Return the model-facing name of a remote operation: ``read`` is ``ssh__read``."""
    return f"{PREFIX}{operation}"


def descriptor(operation: str, handler: Callable[..., Awaitable[Any]]) -> AgentTool:
    """Build one remote tool with framework-generated validation and schema.

    Args:
        operation: ``read``, ``read_file``, ``glob``, ``grep``, ``write_file``, ``edit`` or ``bash``.
        handler: Called with the validated keyword arguments; raises whatever the transport raised.
    """

    def selected(**options: Any) -> Any:
        # Only the requested function needs framework validation/schema generation.
        # Unselected functions are plain definitions, never registered or called.
        if options["name"] == tool_name(operation):
            return tool(**options)
        return lambda function: function

    @selected(
        name=tool_name("read"),
        guidelines=("Paths are on the SSH host, not this machine. The local read tool is still there for local files."),
    )
    async def read(file_path: FilePath, offset: Offset = 1, limit: Limit = 2000) -> Any:
        """Read numbered text or a PNG/JPEG/GIF/WebP image on the SSH host.

        Guidelines:
            - Paths are on the SSH host, not this machine; the local read tool still reads local files.
            - Remote operations require full permission.
        """
        return await handler(file_path=file_path, offset=offset, limit=limit)

    @selected(
        name=tool_name("read_file"),
        guidelines="Text only, on the SSH host. Use offset and limit for the next range.",
    )
    async def read_file(file_path: FilePath, offset: Offset = 1, limit: Limit = 2000) -> Any:
        """Read numbered UTF-8 text on the SSH host, bounded to 2000 lines and 50 KiB.

        Guidelines:
            - Paths are on the SSH host; the local read_file tool is unchanged.
        """
        return await handler(file_path=file_path, offset=offset, limit=limit)

    @selected(name=tool_name("glob"), guidelines="Patterns match the SSH host's filesystem, not this machine.")
    async def glob(pattern: FilePath, max_results: MaxResults = 200) -> Any:
        """Find paths matching a glob on the SSH host.

        Guidelines:
            - Narrow the pattern when results are truncated.
        """
        return await handler(pattern=pattern, max_results=max_results)

    @selected(name=tool_name("grep"), guidelines="Searches the SSH host; narrow file_pattern when truncated.")
    async def grep(
        pattern: FilePath, file_pattern: str = "**/*", case_sensitive: bool = True, max_results: MaxResults = 200
    ) -> Any:
        """Search UTF-8 files on the SSH host with a Python regular expression.

        Guidelines:
            - Narrow file_pattern when results are truncated.
        """
        return await handler(
            pattern=pattern, file_pattern=file_pattern, case_sensitive=case_sensitive, max_results=max_results
        )

    @selected(
        name=tool_name("write_file"),
        execution_mode=ToolExecutionMode.SERIAL,
        guidelines="Writes on the SSH host. Read an existing remote file before replacing it.",
    )
    async def write_file(file_path: FilePath, content: str) -> Any:
        """Atomically write a complete UTF-8 file on the SSH host.

        Guidelines:
            - Paths are on the SSH host; the local write_file tool is unchanged.
        """
        return await handler(file_path=file_path, content=content)

    @selected(
        name=tool_name("edit"),
        execution_mode=ToolExecutionMode.SERIAL,
        guidelines="Exact remote replacement; read first and omit numbered-line prefixes.",
    )
    async def edit(file_path: FilePath, old_string: FilePath, new_string: str, replace_all: bool = False) -> Any:
        """Replace exact text in a file on the SSH host, requiring a unique match by default.

        Guidelines:
            - Paths are on the SSH host. Read first; omit numbered-line prefixes from replacements.
        """
        return await handler(file_path=file_path, old_string=old_string, new_string=new_string, replace_all=replace_all)

    @selected(
        name=tool_name("bash"),
        execution_mode=ToolExecutionMode.SERIAL,
        guidelines="Runs on the SSH host; nonzero exits and timeouts fail with captured output.",
    )
    async def bash(command: FilePath, timeout_seconds: Timeout = 60, work_dir: str | None = None) -> Any:
        """Run a command with the SSH host's /bin/bash.

        Guidelines:
            - This runs on the SSH host, not this machine; the local bash tool is unchanged.
            - Remote operations require full permission; no local sandbox protects the remote host.
        """
        return await handler(command=command, timeout_seconds=timeout_seconds, work_dir=work_dir)

    return {
        "read": read,
        "read_file": read_file,
        "glob": glob,
        "grep": grep,
        "write_file": write_file,
        "edit": edit,
        "bash": bash,
    }[operation]
