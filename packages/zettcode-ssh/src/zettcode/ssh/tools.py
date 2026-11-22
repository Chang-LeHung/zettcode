"""Remote tools built through zett-agent's typed decorator, not handwritten JSON schemas."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from pydantic import Field
from zett_agent.tools.base import AgentTool, ToolExecutionMode, tool

READING = frozenset({"read", "read_file", "glob", "grep"})
ALL = READING | {"write_file", "edit", "bash"}
Handler = Callable[..., Awaitable[Any]]
FilePath = Annotated[str, Field(min_length=1)]
#: Text that is not a path: a replacement, a command, a regular expression.
Text = Annotated[str, Field(min_length=1)]
Offset = Annotated[int, Field(ge=1)]
Limit = Annotated[int, Field(ge=1, le=2000)]
MaxResults = Annotated[int, Field(ge=1, le=5000)]
#: The local shell's ceiling, so a long remote build is not cut at a limit the local tool does not have.
Timeout = Annotated[float, Field(gt=0, le=600)]


def _read(handler: Handler) -> AgentTool:
    @tool
    async def read(file_path: FilePath, offset: Offset = 1, limit: Limit = 2000) -> Any:
        """Read remote numbered text or an image.

        Guidelines:
            - Paths are remote. Never fall back to local files on SSH failure.
            - Remote operations require full permission.
        """
        return await handler(file_path=file_path, offset=offset, limit=limit)

    return read


def _read_file(handler: Handler) -> AgentTool:
    @tool
    async def read_file(file_path: FilePath, offset: Offset = 1, limit: Limit = 2000) -> Any:
        """Read remote numbered UTF-8 text, bounded to 2000 lines and 50 KiB.

        Guidelines:
            - Paths are remote. Use offset and limit for the next range.
        """
        return await handler(file_path=file_path, offset=offset, limit=limit)

    return read_file


def _glob(handler: Handler) -> AgentTool:
    @tool
    async def glob(pattern: Text, max_results: MaxResults = 200) -> Any:
        """Find remote paths matching a glob.

        Guidelines:
            - Narrow the pattern when results are truncated.
        """
        return await handler(pattern=pattern, max_results=max_results)

    return glob


def _grep(handler: Handler) -> AgentTool:
    @tool
    async def grep(
        pattern: Text, file_pattern: str = "**/*", case_sensitive: bool = True, max_results: MaxResults = 200
    ) -> Any:
        """Search remote UTF-8 files with a Python regular expression.

        Guidelines:
            - Narrow file_pattern when results are truncated.
        """
        return await handler(
            pattern=pattern, file_pattern=file_pattern, case_sensitive=case_sensitive, max_results=max_results
        )

    return grep


def _write_file(handler: Handler) -> AgentTool:
    @tool(execution_mode=ToolExecutionMode.SERIAL)
    async def write_file(file_path: FilePath, content: str) -> Any:
        """Atomically write a complete remote UTF-8 file.

        Guidelines:
            - Read an existing file before replacing it. Paths are remote.
        """
        return await handler(file_path=file_path, content=content)

    return write_file


def _edit(handler: Handler) -> AgentTool:
    @tool(execution_mode=ToolExecutionMode.SERIAL)
    async def edit(file_path: FilePath, old_string: Text, new_string: str, replace_all: bool = False) -> Any:
        """Replace exact text in a remote UTF-8 file, requiring a unique match by default.

        Guidelines:
            - Read first; omit numbered-line prefixes from replacements.
        """
        return await handler(file_path=file_path, old_string=old_string, new_string=new_string, replace_all=replace_all)

    return edit


def _bash(handler: Handler) -> AgentTool:
    @tool(execution_mode=ToolExecutionMode.SERIAL)
    async def bash(command: Text, timeout_seconds: Timeout = 60, work_dir: str | None = None) -> Any:
        """Run remote /bin/bash. Nonzero exits and timeouts fail with captured output.

        Guidelines:
            - This runs remotely and cannot launch local daemons.
            - The local safe sandbox cannot protect the remote host.
            - At most 600 seconds, the same ceiling the local shell tool has.
        """
        return await handler(command=command, timeout_seconds=timeout_seconds, work_dir=work_dir)

    return bash


#: One builder per tool. Each ``@tool`` call parses its docstring and builds an input model and schemas, so a
#: backend that asks for one tool builds one, not seven: `on_state` rewrites seven, every intercepted call one more.
_BUILDERS: dict[str, Callable[[Handler], AgentTool]] = {
    "read": _read,
    "read_file": _read_file,
    "glob": _glob,
    "grep": _grep,
    "write_file": _write_file,
    "edit": _edit,
    "bash": _bash,
}


def descriptor(name: str, handler: Handler) -> AgentTool:
    """Build the named remote tool with framework-generated validation and schema."""
    return _BUILDERS[name](handler)
