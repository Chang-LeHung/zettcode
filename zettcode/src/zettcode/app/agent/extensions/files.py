"""The extensions that give an agent its file tools and its shell.

The tools themselves are in :mod:`zettcode.app.agent.tools`; these register them for each request and tell the model
where it is working:

* :class:`FileTools` registers ``read``, ``glob`` and ``grep``, and with ``read_only`` off ``write_file`` and
  ``edit``. It is what a read-only subagent, or one that may edit, is given. A subagent has no shell, so searching
  is a tool of its own there.
* :class:`CodingBundle` is the main agent's: ``read``, ``write_file`` and ``edit``, followed by ``bash``. It has no
  ``glob`` or ``grep``, because it has a shell: ``rg``, ``grep`` and ``find`` do that work, and run through the same
  permission level as any other command.

Neither offers ``read_file``: that is the text-only reader
:class:`~zettcode.app.agent.extensions.capabilities.ModelCapabilities` puts in the place of ``read`` for a model that
does not take images.
"""

from __future__ import annotations

import json
from pathlib import Path

from zett_agent.agent import AgentRunContext
from zett_agent.extensions.base import AgentExtension
from zett_agent.messages import SystemMessage
from zett_agent.tools.base import AgentTool

from ..tools.boundary import Boundary
from ..tools.files import edit, glob, grep, read, write_file
from ..tools.shell import shell_tool

__all__ = ["CodingBundle", "FileTools", "file_tools"]


def file_tools(*, read_only: bool, search: bool = True) -> tuple[AgentTool, ...]:
    """Return the file tools for one mode.

    Args:
        read_only: Offer only the tools that read; otherwise ``write_file`` and ``edit`` too.
        search: Offer ``glob`` and ``grep``. An agent with a shell leaves them out and searches with it.
    """
    reading: tuple[AgentTool, ...] = (read, glob, grep) if search else (read,)
    return reading if read_only else (*reading, write_file, edit)


class FileTools(AgentExtension):
    """Register the file tools, and say which directory their relative paths start from.

    The directory is looked up at every request, since the shell can change it between two of them.
    """

    def __init__(self, *, read_only: bool = False, search: bool = True) -> None:
        """Choose the mode: ``read_only`` keeps the tools that change a file out of the agent's hands."""
        self.read_only = read_only
        self.search = search

    @property
    def tools(self) -> tuple[AgentTool, ...]:
        """Return the tools of the configured mode."""
        return file_tools(read_only=self.read_only, search=self.search)

    async def on_tool(self, context: AgentRunContext) -> None:
        """Register this extension's tools for the request."""
        for registered in self.tools:
            context.register_tool(registered)

    def _environment(self, directory: Path) -> str:
        """Describe the directory every relative path is taken from."""
        return (
            "# Filesystem environment\n"
            f"Current working directory: {json.dumps(str(directory), ensure_ascii=False)}.\n"
            "Relative filesystem paths are resolved from this directory. Absolute paths are also allowed."
        )

    async def on_state(self, context: AgentRunContext) -> None:
        """Put the request's working directory among the system messages, after the ones already there."""
        instructions = [item for item in context.state.messages if isinstance(item, SystemMessage)]
        message = SystemMessage(content=self._environment(Path.cwd().resolve()))
        context.add_message(message, index=len(instructions))


class CodingBundle(FileTools):
    """The main agent's tools: read, write and edit, then the shell, in the working directory the shell starts in.

    There is no ``glob`` or ``grep``: the shell searches. With a ``boundary`` the shell tool runs each command inside
    the sandbox whenever the boundary says so; without one every command runs as it was given.
    """

    def __init__(self, boundary: Boundary | None = None) -> None:
        """Build the shell tool once, over the boundary that decides how it runs."""
        super().__init__(read_only=False, search=False)
        self._shell = shell_tool(boundary)

    @property
    def tools(self) -> tuple[AgentTool, ...]:
        """Return ``read``, ``write_file`` and ``edit``, followed by ``bash``."""
        return (*file_tools(read_only=False, search=False), self._shell)

    def _environment(self, directory: Path) -> str:
        """Add that commands start in the same directory."""
        return f"{super()._environment(directory)}\nShell commands run from this directory."
