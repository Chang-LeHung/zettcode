"""The ``/harness`` command: the just-in-time harness's state, the switch, and the tools a session keeps.

The command used to live with the shell's own commands, which meant the screen it opens belonged to one distribution
and the command to another. Both are here now: the part owns what it shows and the way to see it. It is written
against the plugin contract — the context, the result and ``bottom_panel`` — so the panel is drawn without the
application, and the SDK is only what ``host.client`` is typed as.

``/harness`` with nothing after it opens the read-only panel. ``gen`` turns the harness on and asks the model, as one
ordinary turn, to build a small tool for this workspace; ``reset`` turns it off again and deletes what this session's
harness kept. Both words act on the session and on the harness folder alone: the workspace's own files are never
touched, and the repositories live under ``config.harness_dir``, not in the project.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from zettcode.engine.harness_paths import harness_root, session_directory
from zettcode.error_text import describe_error
from zettcode.plugin_api.commands import CommandContext, CommandResult, Subcommand
from zettcode.plugin_api.panels import bottom_panel
from zettcode.plugin_api.plugin import TuiPlugin

from .page import HARNESS_ROWS, HarnessPage

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zettcode.engine.plugins.context import PluginContext
    from zettcode.plugin_api.commands import CommandHost

#: The words ``/harness`` takes, in the order the completion menu offers them. Both say ``needs_more``: the menu
#: offers them, but Enter on the word alone does not run one — ``/harness `` and Enter stays the panel it was, and
#: ``gen`` (a paid turn) or ``reset`` (a delete) takes a second Enter once the word is in the draft.
SUBCOMMANDS: tuple[Subcommand, ...] = (
    Subcommand("gen", "turn the harness on and have a tool built for this workspace", needs_more=True),
    Subcommand("reset", "turn it off and delete the tools this session kept", needs_more=True),
)

#: What ``/harness gen`` asks the model for. It is one turn of this conversation, so it says what a good tool is and
#: what a report of one has to contain; the reader sees only ``/harness gen`` in the transcript.
GEN_BRIEF = """Build one small tool for this workspace in the just-in-time harness, then report it.

- Call `repo_create` to make the repository and write a focused tool in it with your file tools; a `MANIFEST` that
  declares the tool in `tools = [...]` is what makes `repo_load` check your work. Load it before you claim it works.
- Keep it small and specific: something this workspace needed more than once, one or two tools, the standard library
  where it is enough, and output a reader can use without reading the whole workspace.
- Run it at least once on this workspace and look at what came back, so the report says it works rather than that it
  should. If it fails, fix it and load it again.
- Do not change the workspace's own files: the tool lives in the harness's folder for this session. Reading the
  workspace to decide what to build, and calling your tool to check it, is expected.
- Then report: the repository and the tool's name, what it does, the call you used to check it and what it returned,
  and anything a later reader should know before relying on it.
"""


class HarnessCommand(TuiPlugin):
    """``/harness``: what the harness is doing now, and the two words that change it."""

    name = "harness-command"
    description = (
        "the just-in-time harness: /harness (the panel), gen (build a tool now), reset (drop this session's tools)"
    )

    def activate(self, ctx: PluginContext) -> None:
        """Register ``/harness``; it takes the request slot, so it is refused while a request runs.

        Reading the files costs nothing, and a command that only reports may run beside a request (``/context``
        does); this one draws a panel over the conversation. Its two words need the slot as well: ``gen`` asks for a
        turn of its own, and ``reset`` deletes the folder a request in flight has a harness loaded from.
        """
        if ctx.tui is None:
            return
        ctx.tui.register_command(
            "harness",
            "the just-in-time harness: the panel, and the words that build or drop this session's tools",
            self.harness,
            when_busy="refuse",
            subcommands=SUBCOMMANDS,
        )

    async def harness(self, context: CommandContext) -> CommandResult:
        """Dispatch on the word after the command.

        No word opens the read-only panel; ``gen`` and ``reset`` are the two things a reader may do here. Anything
        else — including the ``on`` and ``off`` this command used to take — is answered with the words it does take,
        rather than changing the harness behind a typo.
        """
        host = context.require_host()
        words = context.argument.split()
        if not words:
            return self._panel(host)
        word = words[0].lower()
        if word not in {subcommand.name for subcommand in SUBCOMMANDS}:
            return CommandResult(message=self._usage(tried=word))
        if len(words) > 1:
            return CommandResult(message=f"`/harness {word}` takes nothing after it.\n\n{self._usage()}")
        if word == "gen":
            return await self._generate(host)
        return self._reset(host)

    def _panel(self, host: CommandHost) -> CommandResult:
        """Open a read-only panel on the just-in-time harness.

        The switch is a plugin setting too: ``/plugins`` turns the harness on or off for the next start, and this page
        says which state it found, where the repositories live, and what this session has written. Nothing on the
        page changes anything; the repositories are read with
        :func:`zett_agent.jit_harness.inspect_repository`, which imports nothing.
        """
        directory = session_directory(host.client.config, host.client.session.id)
        state = "on" if host.client.harness else "off"
        repositories = self._repositories(directory)
        page = HarnessPage(state=state, directory=directory, repositories=repositories, on_close=host.close_page)
        return CommandResult(widget=bottom_panel(page, rows=HARNESS_ROWS))

    async def _generate(self, host: CommandHost) -> CommandResult:
        """Turn the harness on and hand the model the brief, as one ordinary turn of this conversation.

        The switch goes first: the turn mounts the harness's tools when it starts, so a prompt sent before the switch
        moved would be the one request that cannot build anything. The turn is awaited here, the way ``/code-review``
        awaits its own, because the row it draws is the command's answer and the slot stays the command's until it
        ends.
        """
        try:
            on = host.client.use_harness(True)
        except Exception as error:  # noqa: BLE001 - a switch that will not move is a line for the reader, not a crash
            return CommandResult(message=f"**/harness gen** could not turn the harness on: {describe_error(error)}")
        if not on:
            return CommandResult(
                message=(
                    "**/harness gen**: the harness did not turn on, so nothing was generated. "
                    "`/plugins` says whether this build offers it at all."
                )
            )
        if await host.prompt(GEN_BRIEF, shown="/harness gen"):
            return CommandResult()
        return CommandResult(
            message=(
                "**The harness is on**, but no turn was started. Either this session is open in another ZettCode "
                "process — run `/harness gen` there, or close it — or the window is still starting up; run "
                "`/harness gen` again."
            )
        )

    def _reset(self, host: CommandHost) -> CommandResult:
        """Turn the harness off and delete the folder this session's harness kept.

        Nothing is asked first: the folder holds what the model wrote for this session and nothing else, it is
        rebuilt by ``/harness gen``, and the command is only reachable with no request running. What it will not do is
        delete anything outside the harness root — if the session's folder resolves elsewhere (a ``harness_dir`` that
        is a symbolic link out of the harness folder, a pre-workspace installation the move could not merge), the
        reader is told the path instead and deletes it by hand.
        """
        try:
            host.client.use_harness(False)
        except Exception as error:  # noqa: BLE001 - the reader gets a line, not a traceback
            return CommandResult(message=f"**/harness reset** could not turn the harness off: {describe_error(error)}")
        config = host.client.config
        root = harness_root(config)
        directory = session_directory(config, host.client.session.id)
        # Compared after resolution and deleted as written. Resolving is what catches an ancestor that is a link: the
        # folder `rmtree` would reach is not the one the harness root names. Deleting the unresolved path is what
        # keeps a folder that is *itself* a link a refusal (`rmtree` will not follow it) instead of deleting its
        # target. The two steps are not atomic — a link swapped in between them would not be seen — which is the same
        # window every delete by path has.
        if not self._inside(directory, root):
            return CommandResult(
                message=(
                    f"**Harness is off**, but its tools were left alone: this session's folder is `{directory}`, "
                    f"which is not inside the harness folder `{root}`. Delete it by hand if it is the one you mean."
                )
            )
        kept = self._repositories(directory)
        try:
            shutil.rmtree(directory)
        except FileNotFoundError:
            return CommandResult(
                message=f"**Harness is off.** This session had no tools in `{directory}`, so there was nothing to delete."
            )
        except OSError as error:
            return CommandResult(
                message=f"**Harness is off**, but `{directory}` could not be deleted: {describe_error(error)}"
            )
        named = ", ".join(f"`{name}`" for name, _detail in kept) or "the folder held no repository"
        return CommandResult(
            message=(
                f"**Harness is off**, and this session's tools are gone: {named}.\n\n"
                f"The folder was `{directory}`; nothing in the workspace was touched, and `/harness gen` builds "
                "a tool again."
            ),
            notification="Harness reset",
        )

    @staticmethod
    def _inside(directory: Path, root: Path) -> bool:
        """Return whether ``directory`` is strictly below ``root``, links and all — the one test the delete rests on."""
        resolved, resolved_root = directory.resolve(), root.resolve()
        return resolved != resolved_root and resolved.is_relative_to(resolved_root)

    @staticmethod
    def _usage(tried: str = "") -> str:
        """Return the words ``/harness`` takes, for a reader who typed another one.

        Two layers are named, because they are easy to confuse: the two words change **this session**, and
        ``/plugins`` is what a run starts with. A reader who still types ``/harness on`` is looking for the second.
        """
        said = f"`/harness {tried}` is not a word `/harness` takes." if tried else ""
        return (
            f"{said}\n\n"
            "- `/harness` — the panel: whether it is on, where its files are, and this session's repositories\n"
            "- `/harness gen` — turn it on (this session) and have a tool built for this workspace\n"
            "- `/harness reset` — turn it off (this session) and delete the tools this session kept\n"
            "- `/plugins` — whether the harness is offered at all, and whether a run starts with it on"
        ).strip()

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
            try:
                policy = inspect_repository(path)
            except OSError as error:  # a MANIFEST nobody can read is one row, not a failed command
                rows.append((path.name, f"cannot be read: {error}"))
                continue
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
