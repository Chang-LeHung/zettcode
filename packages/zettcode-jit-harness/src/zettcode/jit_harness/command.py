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
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from zettcode.engine.harness_paths import harness_root, session_directory
from zettcode.error_text import describe_error
from zettcode.plugin_api.commands import CommandContext, CommandResult, Subcommand
from zettcode.plugin_api.panels import bottom_panel
from zettcode.plugin_api.plugin import TuiPlugin

from .page import HARNESS_ROWS, HarnessPage

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zettcode.config import ZettCodeConfig
    from zettcode.engine.plugins.context import PluginContext
    from zettcode.plugin_api.commands import CommandHost

#: The words ``/harness`` takes, in the order the completion menu offers them. Both say ``needs_more``: the menu
#: offers them, but Enter on the word alone does not run one — ``/harness `` and Enter stays the panel it was, and
#: ``gen`` (a paid turn) or ``reset`` (a delete) takes a second Enter once the word is in the draft.
SUBCOMMANDS: tuple[Subcommand, ...] = (
    Subcommand("gen", "turn the harness on and have a tool built for this workspace", needs_more=True),
    Subcommand("reset", "turn it off and delete the tools this session kept", needs_more=True),
)

#: What both words answer when another process holds the session. ``when_busy`` sees this process's requests only, and
#: the folder one word deletes is where the other process's harness is loaded from, so the command asks the session
#: for itself before it changes anything at all.
LOCKED = (
    "**Nothing was changed**: this session is open in another ZettCode process, which holds it. "
    "Run this command there, or close that one and try again."
)

#: What ``/harness reset`` answers when this window's own harness for the session is still in a request. It cannot
#: happen while the shell refuses a busy command, and it is said rather than assumed.
HARNESS_IN_USE = (
    "**Harness is off for this run**, and nothing was deleted: this session's harness is still loaded by a request "
    "that has not ended. Run `/harness reset` again in a moment."
)

#: What ``/harness gen`` asks the model for. It is one turn of this conversation, so it says what a good tool is and
#: what a report of one has to contain; the reader sees only ``/harness gen`` in the transcript.
GEN_BRIEF = """Build one small tool for this workspace in the just-in-time harness, then report it.

- Call `repo_create` to make the repository and write a focused tool in it with your file tools; a `MANIFEST` that
  declares the tool in `tools = [...]` is what makes `repo_load` check your work. Load it before you claim it works.
  A session keeps one repository: if this one already has it, reuse it rather than creating a second.
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

    def __init__(self, release: Callable[[str], bool] | None = None) -> None:
        """Hold the way to close one session's harness child, which deleting its folder needs.

        Args:
            release: Called with the session id before the folder goes; ``False`` means a request in flight still
                holds the child. The plugin passes the extension this process built, so a delete does not have to
                remove a folder a live child process is working in (Windows refuses that). A command built without
                one — in a test — has nothing to close.
        """
        self._release: Callable[[str], bool] = release if release is not None else (lambda session_id: True)

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
        moved would be the one request that cannot build anything. The session is asked for before that, for the same
        reason ``reset`` asks: a turn cannot start in a session another process holds, and turning the switch on for a
        run that then does nothing is a change nobody asked for. The turn is awaited here, the way ``/code-review``
        awaits its own, because the row it draws is the command's answer and the slot stays the command's until it
        ends.
        """
        if host.client.session.locked:
            return CommandResult(message=LOCKED)
        host.client.use_harness(True)
        if await host.prompt(GEN_BRIEF, shown="/harness gen"):
            return CommandResult()
        return CommandResult(
            message=(
                "**The harness is on**, but the turn did not start: the window said why, above the composer, for a "
                "moment. Run `/harness gen` again when it is free."
            )
        )

    def _reset(self, host: CommandHost) -> CommandResult:
        """Turn the harness off and delete the folder this session's harness kept.

        Nothing is asked first: the folder holds what the model wrote for this session and nothing else, and it is
        rebuilt by ``/harness gen``. Two things are asked *of* it, though, and in this order. The session has to be
        this process's — the folder is where another process's harness is loaded from, and ``when_busy`` cannot see
        that process — before the path is even worked out, because naming it can move a pre-workspace folder into
        place. And the folder has to be inside the harness root: one that is itself a link, resolves elsewhere, or is
        a pre-workspace installation the move could not merge is reported with its path and left alone. A
        ``harness_dir`` that is itself a link is not that case; it is the harness folder, resolved on both sides. A
        copy the move could not take — it failed, or it merged only part of a folder — is named in the answer instead
        of being called gone, because the next request folds it back in.
        """
        if host.client.session.locked:
            return CommandResult(message=LOCKED)
        host.client.use_harness(False)
        config = host.client.config
        root = harness_root(config)
        directory = session_directory(config, host.client.session.id)
        # Deleted as written, after two checks. A session folder that is itself a link is refused here, in a sentence:
        # `rmtree` refuses it too, but as a bare OSError. Resolution then decides whether the folder `rmtree` would
        # reach is one the harness root names — deleting the unresolved path is what keeps a link a refusal rather
        # than a delete of its target. The steps are not atomic — a link swapped in between them would not be seen —
        # which is the same window every delete by path has.
        if directory.is_symlink():
            return CommandResult(
                message=(
                    f"**Harness is off for this run**, but its tools were left alone: `{directory}` is a symbolic "
                    "link, and this command does not delete through a link. Remove it by hand if it is yours."
                )
            )
        if not self._inside(directory, root):
            return CommandResult(
                message=(
                    f"**Harness is off for this run**, but its tools were left alone: this session's folder is "
                    f"`{directory}`, which is not inside the harness folder `{root}`. Delete it by hand if it is the "
                    "one you mean."
                )
            )
        kept = self._repositories(directory)
        # The folder is where this session's harness child works, and Windows will not remove a folder a live process
        # sits in. Closing the child drops the tools it had loaded too, so what is gone is the folder and the tools
        # alike; the next request builds a new one from whatever is on disk then.
        if not self._release(host.client.session.id):
            return CommandResult(message=HARNESS_IN_USE)
        try:
            shutil.rmtree(directory)
        except FileNotFoundError:
            return CommandResult(
                message=(
                    f"**Harness is off for this run.** This session had no tools in `{directory}`, so there was "
                    "nothing to delete."
                )
            )
        except OSError as error:
            return CommandResult(
                message=(
                    f"**Harness is off for this run**, but `{directory}` could not be deleted: "
                    f"{describe_error(error)}. Fix what stopped it and run `/harness reset` again."
                )
            )
        named = ", ".join(f"`{name}`" for name, _detail in kept) or "no repository in it"
        leaving = self._legacy(config, host.client.session.id)
        if leaving is not None:
            # The move merges what it can and leaves the rest: the next request folds that copy back in, so the folder
            # is not the whole story and the message must not say it is.
            return CommandResult(
                message=(
                    f"**Harness is off for this run**, and `{directory}` is gone ({named}).\n\n"
                    f"A copy from before the workspace level is still at `{leaving}`; the next request merges it back "
                    "in, so run `/harness reset` again to drop that one too. Nothing in the workspace was touched."
                ),
                notification="Harness reset",
            )
        return CommandResult(
            message=(
                f"**Harness is off for this run**, and this session's tools are gone with their folder: {named}.\n\n"
                f"The folder was `{directory}`; nothing in the workspace was touched, and `/harness gen` builds "
                "a tool again."
            ),
            notification="Harness reset",
        )

    @staticmethod
    def _legacy(config: ZettCodeConfig, session_id: str) -> Path | None:
        """Return a pre-workspace copy of this session's folder that the delete leaves behind, if there is one."""
        from zett_agent.jit_harness.repo import session_directory_name

        copy = config.harness_dir / session_directory_name(session_id)
        return copy if copy.is_dir() else None

    @staticmethod
    def _inside(directory: Path, root: Path) -> bool:
        """Return whether ``directory`` is strictly below ``root``, links and all — the one test the delete rests on.

        ``resolved != resolved_root`` compares a path with its own parent today: ``session_directory_name`` never
        yields an empty name, so the two cannot be equal. It is kept for the change that would make them so — a
        ``move_session`` that returned the root itself — because the cost of the check is one comparison and the cost
        of being wrong is a deleted harness folder.
        """
        resolved, resolved_root = directory.resolve(), root.resolve()
        return resolved != resolved_root and resolved.is_relative_to(resolved_root)

    @staticmethod
    def _usage(tried: str = "") -> str:
        """Return the words ``/harness`` takes, for a reader who typed another one.

        Two layers are named, because they are easy to confuse: the switch is this run's — every session in this
        window sees it — while the folder ``reset`` deletes belongs to one session. ``/plugins`` is what a run starts
        with.
        """
        said = f"`/harness {tried}` is not a word `/harness` takes." if tried else ""
        return (
            f"{said}\n\n"
            "- `/harness` — the panel: whether it is on, where its files are, and this session's repositories\n"
            "- `/harness gen` — turn it on (for this run) and have a tool built for this workspace\n"
            "- `/harness reset` — turn it off (for this run) and delete the tools this session kept\n"
            "- `/plugins` — whether a run starts with it on, from `harness.jit`"
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
