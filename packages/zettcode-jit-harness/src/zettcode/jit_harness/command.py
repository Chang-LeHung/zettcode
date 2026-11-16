"""The ``/harness`` command: the just-in-time harness's state, the switch, and the tools a session keeps.

The command used to live with the shell's own commands, which meant the screen it opens belonged to one distribution
and the command to another. Both are here now: the part owns what it shows and the way to see it. It is written
against the plugin contract — the context and the result — so the panel is drawn without the
application, and the SDK is only what ``host.client`` is typed as.

``/harness`` with nothing after it opens the session picker: every session with a harness, the current one first and
selected; Enter borrows that session's harness for the current conversation, and the current row returns to its own.
``gen`` turns the harness on and asks the model, as one
ordinary turn, to build a small tool for this workspace — the rest of the line, if there is any, is what the reader
wants built and is handed on as a requirement rather than as advice; ``reset`` turns it off again so later requests
have none of its tools, and deletes nothing. Both words act on the switch and on the harness folder alone: the
workspace's own files are never touched, and the repositories live under ``config.harness_dir``, not in the project.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from zettcode.engine.harness_paths import existing_session_path, session_directory
from zettcode.plugin_api.commands import CommandContext, CommandResult
from zettcode.plugin_api.plugin import TuiPlugin
from zettcode.tui.render import truncate

from .brief import (
    GEN_ASKED,
    GEN_BRIEF,
    GEN_FLOOR_LAST,
    LOCKED,
    MAX_DESCRIPTION,
    MAX_SHOWN,
    SUBCOMMANDS,
    brief_for,
    split_argument,
)
from .page import HarnessPage, HarnessTarget, TableRow, TableView
from .selection import HARNESS_CHOICES, HarnessChoice, HarnessChoices

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zettcode.engine.plugins.context import PluginContext
    from zettcode.plugin_api.commands import CommandHost, CommandUi

#: Said when a turn this reader asked for did not start and they had written something: the line never went out, and a
#: reader who pasted a paragraph has to be told that rather than find out by looking. The draft is in the composer's
#: history, so one Up brings it back.
NOT_KEPT = "What you wrote after the word was not sent — press Up to bring the line back."

__all__ = [
    "GEN_ASKED",
    "GEN_BRIEF",
    "GEN_FLOOR_LAST",
    "LOCKED",
    "MAX_DESCRIPTION",
    "MAX_SHOWN",
    "NOT_KEPT",
    "SUBCOMMANDS",
    "HarnessCommand",
    "brief_for",
    "directory_of",
    "shown_for",
    "split_argument",
]


def directory_of(host: CommandHost) -> Path:
    """Return this session's harness folder — the one the panel lists and ``reset`` names rather than empties."""
    return session_directory(host.client.config, host.client.session.id)


def shown_for(description: str) -> str:
    """Return what the transcript draws for the turn: the command, on one row, shortened when it is long.

    One line on purpose, not because a conversation row cannot hold more — a row with line breaks is drawn with them.
    A description pasted with its own breaks would otherwise fill the screen, and the model reads it verbatim further
    down anyway, so the breaks become single spaces here. The budget is columns, not characters: a row of 120 Chinese
    characters is 240 columns, and the framework's own `truncate` is what knows the difference.
    """
    asked = description.strip().replace("\r\n", " ").replace("\r", " ").replace("\n", " ").replace("\t", " ")
    line = f"/harness gen {asked}" if asked else "/harness gen"
    return truncate(line, MAX_SHOWN)


class HarnessCommand(TuiPlugin):
    """``/harness``: what the harness is doing now, and the two words that change it."""

    name = "harness-command"
    description = (
        "the just-in-time harness: /harness (the panel), gen [what you want] (build a tool), reset (switch back)"
    )

    def __init__(self) -> None:
        self.choices: HarnessChoices | None = None

    def activate(self, ctx: PluginContext) -> None:
        """Register ``/harness``; it takes the request slot, so it is refused while a request runs.

        Reading the files costs nothing, and a command that only reports may run beside a request (``/context``
        does); this one draws a panel over the conversation. Its two words need the slot as well: ``gen`` asks for a
        turn of its own, and ``reset`` is a switch the next request reads.
        """
        if ctx.tui is None:
            return
        self.choices = ctx.find(HARNESS_CHOICES, HarnessChoices)
        ctx.tui.register_command(
            "harness",
            "the just-in-time harness: the panel, and the words that turn it on or hand it back",
            self.harness,
            when_busy="refuse",
            subcommands=SUBCOMMANDS,
        )

    async def harness(self, context: CommandContext) -> CommandResult:
        """Dispatch on the word after the command.

        No word opens the read-only panel; ``gen`` and ``reset`` are the two things a reader may do here. Anything
        else — including the ``on`` and ``off`` this command used to take — is answered with the words it does take,
        rather than changing the harness behind a typo. ``gen`` takes the rest of the line as the reader's own
        description of what they want built; ``reset`` takes nothing after the word, because there is nothing to say
        about a switch.
        """
        host = context.require_host()
        word, rest = split_argument(context.argument)
        if not word:
            return await self._panel(host)
        if word == "gen":
            return await self._generate(host, rest, ui=context.ui)
        if word == "reset":
            if rest:
                return CommandResult(message=f"`/harness reset` takes nothing after it.\n\n{self._usage()}")
            return self._reset(host)
        return CommandResult(message=self._usage(tried=word))

    async def _panel(self, host: CommandHost) -> CommandResult:
        """Open the picker over every harness directory under the configured harness root.

        The current session is always a row, even before it has a folder; Enter on another row borrows that directory,
        and Enter on the current row returns to the session's own. Directories are grouped by workspace when they are
        one level down, and legacy session directories are still rows. The panel reads the tree, never imports a
        plugin, and never moves a folder.
        """
        current = host.client.session.id
        config = host.client.config
        current_directory = existing_session_path(config, current)
        root = config.harness_dir
        choice = self.choices.target(current) if self.choices is not None else None
        effective_directory = choice.directory if choice is not None else current_directory
        current_title = await asyncio.to_thread(lambda: getattr(host.client.session, "title", None))
        rows = await asyncio.to_thread(
            self._session_rows,
            current,
            current_title,
            current_directory,
            root,
            choice,
            config.store,
        )
        tools = await asyncio.to_thread(self._tool_rows, host, current, effective_directory)
        files = await asyncio.to_thread(self._file_rows, effective_directory)
        state = "on" if host.client.harness else "off"
        page = HarnessPage(
            state=state,
            directory=root,
            views=(
                TableView(
                    "Harnesses",
                    ("SESSION", "TITLE", "REPOSITORY", "DESCRIPTION"),
                    rows,
                    "accent = current session · enter borrow · esc close",
                ),
                TableView(
                    "Tools",
                    ("TOOL", "SOURCE", "STATUS", "DESCRIPTION"),
                    tools,
                    "accent = active · error colour = banned · esc close",
                ),
                TableView("Files", ("FILE", "DESCRIPTION", "SIZE", "PATH"), files),
            ),
            on_switch=lambda target: self._switch(host, current, target),
            on_close=host.close_page,
        )
        return CommandResult(widget=page)

    @classmethod
    def _session_rows(
        cls,
        current: str,
        current_title: str | None,
        current_directory: Path,
        root: Path,
        choice: HarnessChoice | None,
        store: Path,
    ) -> list[TableRow]:
        """Scan the harness tree off the event loop, one row per repository."""
        harnesses = cls._all_harnesses(root)
        titles = cls._titles(store, {current, *(directory.name for directory, _ in harnesses)})
        current_label = cls._session_label(current, current_title)
        current_target = HarnessTarget(current_label, current_directory)
        current_title = current_title or ""
        if choice is not None:
            rows = [
                TableRow(
                    current_target,
                    (current, current_title, "", f"using {choice.label}"),
                    True,
                )
            ]
        else:
            rows = cls._repo_rows(current_directory, current_target, current, current_title, current=True)
            if not rows:
                rows = [TableRow(current_target, (current, current_title, "", "No harness yet"), True)]
        seen = {current_directory.resolve()}
        for directory, workspace in harnesses:
            try:
                if directory.resolve() in seen:
                    continue
            except OSError:
                continue
            title = titles.get(directory.name, "")
            label = cls._session_label(directory.name, title)
            if workspace:
                label = f"{workspace}/{label}"
            target = HarnessTarget(label, directory)
            detail_prefix = "" if choice is None or choice.directory != directory else " · in use"
            found = cls._repo_rows(directory, target, directory.name, title)
            if not found:
                found = [TableRow(target, (directory.name, title, "", f"No repositories yet{detail_prefix}"))]
            elif detail_prefix:
                found = [TableRow(row.target, (*row.cells[:3], f"{row.cells[3]}{detail_prefix}")) for row in found]
            rows.extend(found)
        return rows

    @classmethod
    def _repo_rows(
        cls, directory: Path, target: HarnessTarget, session: str, title: str, *, current: bool = False
    ) -> list[TableRow]:
        """Return one row per repository, with its manifest description when it has one."""
        from zett_agent.jit_harness import inspect_repository

        if not directory.is_dir():
            return []
        try:
            repositories = sorted(path for path in directory.iterdir() if (path / "__init__.py").is_file())
        except OSError as error:
            return [TableRow(target, (session, title, "", f"cannot be read: {error}"), current)]
        rows: list[TableRow] = []
        for repository in repositories:
            try:
                policy = inspect_repository(repository)
            except OSError as error:
                description = f"cannot be read: {error}"
            else:
                if policy.ok and policy.manifest is not None:
                    description = policy.manifest.description or "(no description)"
                else:
                    description = "cannot load: " + "; ".join(policy.problems)
            rows.append(TableRow(target, (session, title, repository.name, description), current))
        return rows

    @classmethod
    def _tool_rows(cls, host: CommandHost, current: str, directory: Path) -> list[TableRow]:
        """Return request tools now, then the tools in the effective folder's JIT repositories."""
        from zett_agent.jit_harness import inspect_repository

        runtime = getattr(getattr(host, "agent", None), "runtime", None)
        context = getattr(runtime, "context", None)
        offered = tuple(getattr(context, "tools", ()) or ())
        active = {getattr(tool, "name", ""): tool for tool in offered if getattr(tool, "name", "")}
        try:
            repositories = sorted(path for path in directory.iterdir() if (path / "__init__.py").is_file())
        except OSError:
            repositories = []
        jit: list[tuple[str, Path, str, set[str]]] = []
        for repository in repositories:
            try:
                policy = inspect_repository(repository)
            except OSError:
                continue
            if policy.manifest is None:
                continue
            banned = set(policy.banned)
            for name in policy.manifest.tools:
                jit.append((name, repository, policy.manifest.description, banned))
        jit_names = {name for name, _repository, _description, _banned in jit}
        rows = [
            TableRow(None, (name, "request", "active", getattr(tool, "description", "")), current=True)
            for name, tool in sorted(active.items())
            if name not in jit_names
        ]
        for name, repository, description, banned in jit:
            status = "banned" if name in banned else "active" if name in active else "available"
            rows.append(
                TableRow(
                    None,
                    (name, f"jit/{repository.name}", status, description),
                    current=status == "active",
                    danger=status == "banned",
                )
            )
        if not rows:
            rows = [TableRow(None, ("No tools yet", "", "", ""))]
        return rows

    @staticmethod
    def _file_rows(directory: Path) -> list[TableRow]:
        """List the Markdown files under the effective harness folder."""
        try:
            files = sorted(path for path in directory.rglob("*.md") if path.is_file())
        except OSError:
            return [TableRow(None, ("No Markdown files yet", "", "", ""))]
        rows: list[TableRow] = []
        for path in files:
            try:
                relative = path.relative_to(directory)
                size = path.stat().st_size
            except OSError:
                continue
            rows.append(
                TableRow(
                    None,
                    (relative.name, HarnessCommand._markdown_description(path), f"{size:,} B", str(relative.parent)),
                )
            )
        return rows or [TableRow(None, ("No Markdown files yet", "", "", ""))]

    @staticmethod
    def _markdown_description(path: Path) -> str:
        """Return the first heading, paragraph or front-matter description in a Markdown file."""
        try:
            with path.open(encoding="utf-8", errors="replace") as handle:
                lines = [handle.readline() for _ in range(30)]
        except OSError as error:
            return f"cannot be read: {error}"
        title = ""
        for line in lines:
            text = line.strip()
            if text.startswith("description:"):
                return text.partition(":")[2].strip().strip("\"'") or "(no description)"
            if text.startswith("title:") and not title:
                title = text.partition(":")[2].strip().strip("\"'")
                continue
            if not text or text in {"---", "..."} or text.startswith(("```", "<!--")):
                continue
            text = text.lstrip("#").lstrip(">*- ").strip()
            if text:
                return text[:120]
        return title or "(no description)"

    @staticmethod
    def _titles(store: Path, names: set[str]) -> dict[str, str]:
        """Read titles only for listed sessions, using the store's own metadata reader."""
        from zettcode.engine.storage.metadata import SESSION_METADATA_FILE, read_session_metadata

        titles: dict[str, str] = {}
        try:
            workspaces = [path for path in store.iterdir() if path.is_dir()]
        except OSError:
            return titles
        for workspace in workspaces:
            try:
                sessions = [path for path in workspace.iterdir() if path.is_dir()]
            except OSError:
                continue
            for session in sessions:
                if session.name not in names:
                    continue
                metadata = read_session_metadata(session / SESSION_METADATA_FILE, session.name)
                if metadata is not None and metadata.title:
                    titles[session.name] = metadata.title
        return titles

    @staticmethod
    def _session_label(session_id: str, title: str | None) -> str:
        """Return the two facts a row needs: the session id and its title, when they differ."""
        return f"{session_id} · {title}" if title and title != session_id else session_id

    @classmethod
    def _all_harnesses(cls, root: Path) -> list[tuple[Path, str]]:
        """Return every listed session directory under ``root`` and its workspace name, if any.

        A session is recognised by a repository directly inside it. An empty legacy folder is not distinguishable
        from an empty workspace, so it is not a row until it has a repository.
        """
        if not root.is_dir():
            return []
        found: list[tuple[Path, str]] = []
        try:
            children = sorted(root.iterdir(), key=lambda path: path.name)
        except OSError:
            return []
        for child in children:
            if not child.is_dir():
                continue
            try:
                direct = [path for path in child.iterdir() if path.is_dir() and (path / "__init__.py").is_file()]
            except OSError:
                continue
            if direct:
                # A legacy session directory sits directly under the harness root.
                found.append((child, ""))
                continue
            try:
                sessions = [path for path in child.iterdir() if path.is_dir()]
            except OSError:
                continue
            for session in sessions:
                found.append((session, child.name))
        return found

    def _switch(self, host: CommandHost, current: str, target: HarnessTarget) -> None:
        """Borrow the selected harness, or close the page on the current row."""
        if target.directory == existing_session_path(host.client.config, current):
            if self.choices is not None:
                self.choices.clear(current)
            host.close_page()
            return
        if self.choices is None:
            host.transcript.notice("Harness borrowing is unavailable in this window.")
            host.close_page()
            return
        if not target.directory.is_dir():
            host.transcript.notice(f"That harness folder is gone: `{target.directory}`.")
            host.close_page()
            return
        self.choices.select(current, target.label, target.directory)
        host.close_page()

    async def _generate(self, host: CommandHost, description: str, *, ui: CommandUi) -> CommandResult:
        """Turn the harness on and hand the model the brief, as one ordinary turn of this conversation.

        The switch goes first: the turn mounts the harness's tools when it starts, so a prompt sent before the switch
        moved would be the one request that cannot build anything. The session is asked for before that: a turn cannot
        start in a session another process holds, and turning the switch on for a run that then does nothing is a
        change nobody asked for. The turn is awaited here, the way ``/code-review`` awaits its own, because the row it
        draws is the command's answer and the slot stays the command's until it ends.

        ``description`` is what the reader typed after ``gen``, kept as they typed it: it is handed to the model after
        the brief, marked as a requirement, and what the transcript shows is the command with it rather than the brief.
        """
        if host.client.session.locked:
            return CommandResult(message=f"{LOCKED}\n\n{NOT_KEPT}" if description.strip() else LOCKED)
        host.client.use_harness(True)
        asked = description.strip()
        if len(asked) > MAX_DESCRIPTION:
            # Said before the turn, not after it: a reader who pasted 6,000 characters has to know that the last 2,000
            # are not going out before the model builds anything, and the model is told the same in the brief.
            lost = len(asked) - MAX_DESCRIPTION
            ui.notice(
                f"Your description was cut at {MAX_DESCRIPTION} characters: the last {lost} "
                f"{'character was' if lost == 1 else 'characters were'} not sent."
            )
        if await host.prompt(brief_for(description), shown=shown_for(description)):
            return CommandResult()
        unsent = f" {NOT_KEPT}" if description.strip() else ""
        return CommandResult(
            message=(
                "**The harness is on**, but the turn did not start: the window said why, above the composer, for a "
                f"moment. Run `/harness gen` again when it is free.{unsent}"
            )
        )

    def _reset(self, host: CommandHost) -> CommandResult:
        """Turn the just-in-time harness off, and leave everything it wrote where it is.

        ``/harness reset`` means what the reader said when they asked for it: no more just-in-time harness — later
        requests have none of its tools, which is what the framework ships before a reader asks for one. Nothing is
        deleted: the folder this session's tools live in is the model's work, and a command whose job is to flip a
        switch does not get to throw it away. The path is named, and whether it is there at all, so a reader who does
        want it gone knows exactly what to remove.
        """
        host.client.use_harness(False)
        current = host.client.session.id
        choice = self.choices.target(current) if self.choices is not None else None
        directory = choice.directory if choice is not None else directory_of(host)
        borrowed = f" It is borrowed from `{choice.label}`." if choice is not None else ""
        if directory.is_dir():
            kept = (
                f"Nothing was deleted: the folder this session's tools live in is still there (`{directory}`).{borrowed} "
                "Remove it yourself if you want them gone — on Windows close ZettCode first, because the harness's "
                "child process works in there — or run `/harness gen` to build on them."
            )
        elif directory.exists() or directory.is_symlink():
            kept = (
                f"Nothing was deleted: `{directory}` is there but is not a folder, so it was left as it is.{borrowed} "
                "`/harness gen` cannot make the folder while that is in the way: move it aside first."
            )
        else:
            kept = (
                f"Nothing was deleted: there is no folder at `{directory}`, so there is nothing here to remove.{borrowed} "
                "`/harness gen` builds one when you want it."
            )
        return CommandResult(
            message=f"**Harness is off for this run**: later requests have none of its tools.\n\n{kept}",
            notification="Harness reset",
        )

    @staticmethod
    def _usage(tried: str = "") -> str:
        """Return the words ``/harness`` takes, for a reader who typed another one.

        Two layers are named, because they are easy to confuse: the switch is this run's — every session in this
        window sees it — while the folder the panel and ``reset`` name belongs to one session, and neither word deletes
        it. ``/plugins`` is what a run starts with.
        """
        said = f"`/harness {tried}` is not a word `/harness` takes." if tried else ""
        return (
            f"{said}\n\n"
            "- `/harness` — every session's harness; Enter borrows the selected one, and the current row returns to its own\n"
            "- `/harness gen [description]` — turn it on (for this run) and have a tool built; anything you write after\n"
            "  the word says what you want, and the model is told to treat it as a requirement\n"
            "- `/harness reset` — turn it off (for this run), so later requests have none of its tools; what this\n"
            "  session wrote stays where it is\n"
            "- `/plugins` — whether a run starts with it on, from `harness.jit`"
        ).strip()
