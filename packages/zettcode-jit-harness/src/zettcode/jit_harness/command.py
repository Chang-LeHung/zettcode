"""The ``/harness`` command: a read-only panel on the just-in-time harness, shipped with the harness itself.

The command used to live with the shell's own commands, which meant the screen it opens belonged to one distribution
and the command to another. Both are here now: the part owns what it shows and the way to see it. It is written
against the plugin contract — the context, the result and ``bottom_panel`` — so the panel is drawn without the
application, and the SDK is only what ``host.client`` is typed as.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from zettcode.engine.harness_paths import session_directory
from zettcode.plugin_api.commands import CommandContext, CommandResult
from zettcode.plugin_api.panels import bottom_panel
from zettcode.plugin_api.plugin import TuiPlugin

from .page import HARNESS_ROWS, HarnessPage

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zettcode.engine.plugins.context import PluginContext


class HarnessCommand(TuiPlugin):
    """``/harness``: what the harness is doing now, where its files are, and what the model has written."""

    name = "harness-command"
    description = "the just-in-time harness's state and this session's repositories"

    def activate(self, ctx: PluginContext) -> None:
        """Register ``/harness``; it opens a page, so it is refused while a request runs rather than opened over it.

        Reading the files costs nothing, and a command that only reports may run beside a request (``/context``
        does); this one draws a panel over the conversation, which is why it waits for the request to end.
        """
        if ctx.tui is None:
            return
        ctx.tui.register_command(
            "harness",
            "what the just-in-time harness is doing, and where its tools are",
            self.harness,
            when_busy="refuse",
        )

    async def harness(self, context: CommandContext) -> CommandResult:
        """Open a read-only panel on the just-in-time harness.

        The switch is a plugin setting now: `/plugins` turns the harness on or off for the next start, and this page
        says which state it found, where the repositories live, and what this session has written. Nothing on the
        page changes anything; the repositories are read with
        :func:`zett_agent.jit_harness.inspect_repository`, which imports nothing.
        """
        host = context.require_host()
        if context.argument.strip():
            return CommandResult(
                message="/harness no longer takes on or off; /plugins switches the harness, and /harness shows it."
            )
        directory = session_directory(host.client.config, host.client.session.id)
        state = "on" if host.client.harness else "off"
        repositories = self._repositories(directory)
        page = HarnessPage(state=state, directory=directory, repositories=repositories, on_close=host.close_page)
        return CommandResult(widget=bottom_panel(page, rows=HARNESS_ROWS))

    def _repositories(self, directory: Path) -> list[tuple[str, str]]:
        """Return this session's repositories as ``(name, detail)``: what the files declare, or why they cannot load."""
        from zett_agent.jit_harness import inspect_repository

        try:
            found = (
                sorted(path for path in directory.iterdir() if (path / "__init__.py").is_file())
                if directory.is_dir()
                else []
            )
        except OSError as error:
            return [("Could not be read", str(error))]
        rows: list[tuple[str, str]] = []
        for path in found:
            policy = inspect_repository(path)
            if not policy.ok or policy.manifest is None:
                rows.append((path.name, f"cannot load: {'; '.join(policy.problems)}"))
                continue
            manifest = policy.manifest
            declared = (
                f"declares {len(manifest.tools)} tool{'s' if len(manifest.tools) != 1 else ''}"
                if manifest.tools
                else "declares no tools"
            )
            banned = f"; {len(policy.banned)} banned" if policy.banned else ""
            rows.append(
                (path.name, f"{manifest.name} {manifest.version} — {manifest.description} ({declared}{banned})")
            )
        return rows
