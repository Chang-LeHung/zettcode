"""Session switching, restoration, and the background title.

Switching sessions replaces the visible history, restores the store's title,
and asks the agent to name a new session once, off the composer's critical path.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

from zettcode.app.plugins.state import Activity
from zettcode.collector import collector_paused
from zettcode.sdk.types import StoredSession
from zettcode.tui import ELLIPSIS, SEPARATOR, Theme

from ..agent.conversation.presenters import block_for
from ..agent.conversation.replay import Replayed, replay
from ..commands import COMMAND_ERRORS
from .shell import ShellState
from .widgets import WELCOME

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zettcode.config import ModelConfig


#: Seconds between the tries to take the lock of a session another process has open: long enough to cost
#: nothing, short enough that the session is the reader's within a moment of the other process letting go.
LOCK_POLL_SECONDS = 2.0


@dataclass(frozen=True, slots=True)
class LoadedSession:
    """A stored session and the rows the terminal built from it, ready to install.

    Attributes:
        stored: What the engine read: the parsed file, its totals, title and model.
        replayed: The rows the terminal replayed it into, already measured.
    """

    stored: StoredSession
    replayed: Replayed


class SessionMixin(ShellState):
    """Switch the active session and keep its title current."""

    #: The task that keeps trying to take the lock of a session another process has open.
    _lock_watch: asyncio.Task[None] | None
    #: Whether the reader has been told the session is read-only here, so that is said once.
    _lock_said: str | None

    # -- the lock on the session -------------------------------------------------------------------
    def _sync_lock(self) -> None:
        """Make the composer, the messaging and the watcher agree with who holds the active session's lock.

        A session another process has open is shown and not written to: the composer shows a lock and takes
        only commands, the session does not register with the broker (so nobody sends it a message it would
        turn into a write), and a task tries again every few seconds. Called wherever the active session may
        have changed: starting, resuming, forking, ``/new``.
        """
        locked = self.client.session.locked
        self.composer.locked = locked
        if not locked:
            self._lock_said = None
            self._stop_lock_watch()
        else:
            if self._lock_said != self.client.session.id:
                self._lock_said = self.client.session.id
                self.transcript.notice(
                    "This session is open in another ZettCode process, so it is read-only here. "
                    "It unlocks by itself when that one lets go; /new starts a new session, "
                    "/fork carries this conversation into one."
                )
            self._start_lock_watch()
        self._sync_messaging()
        self.app.invalidate()

    def _start_lock_watch(self) -> None:
        """Begin trying to take the lock again, when there is a loop to try on."""
        if self._lock_watch is not None and not self._lock_watch.done():
            return
        try:
            self._lock_watch = asyncio.get_running_loop().create_task(self._watch_lock())
        except RuntimeError:
            self._lock_watch = None  # the command line builds the shell with no loop; starting it again starts this

    def _stop_lock_watch(self) -> None:
        """Stop trying: the session is ours, or another one is open."""
        watch, self._lock_watch = self._lock_watch, None
        if watch is not None and watch is not asyncio.current_task():
            watch.cancel()

    async def _watch_lock(self) -> None:
        """Try to take the lock until it is had, then load the session again: it moved while it was not ours."""
        session_id = self.client.session.id
        while self.client.session.locked and self.client.session.id == session_id:
            await asyncio.sleep(LOCK_POLL_SECONDS)
            if self._busy or self.client.session.id != session_id:
                continue
            if self.client.session.retake():
                await self._lock_taken(session_id)
                return

    def _retry_lock(self) -> None:
        """Enter on a locked composer: try for the lock now, and say how it went."""
        if self._busy:
            return
        session_id = self.client.session.id
        if self.client.session.retake():
            self._task = asyncio.create_task(self._lock_taken(session_id))
        else:
            self.flash("still open in another ZettCode process", level="error")

    async def _lock_taken(self, session_id: str) -> None:
        """The other process let go: read the session again, so what it wrote is what is on screen, and say so.

        The conversation shown was read when the lock was not ours, and the process that had it has been
        writing to it since; typing into that would continue a conversation that is no longer there.
        """
        if self._busy:
            return
        await self._switch_session(session_id)
        if self.client.session.id == session_id and not self.client.session.locked:
            self.transcript.notice("The other process has let go of this session; it is yours now.")
            self.app.invalidate()

    async def rename_session(self, title: str) -> str:
        """Name the active session and show it in the status line.

        Args:
            title: Name the user typed; the store rejects a blank or over-long
                one, which the command turns into a notice.

        Returns:
            The stored title, so the command can confirm it.
        """
        renamed = await self.client.session.rename(title)
        self._session_title = renamed
        self._sync_messaging()
        self.app.invalidate()
        return renamed

    def select_session(self, session_id: str) -> None:
        """Switch to the session picked in the panel, and close the panel.

        Resuming reads and rebuilds a whole session, which on a long one is a
        noticeable part of a second; it runs behind the interface rather than in
        front of it, as a command does, so the panel closes at once and the status
        line says what is happening while the rows are made.
        """
        if self._busy:
            return  # a request or an earlier resume is already in flight
        # Close the panel first: the toast is its own screen, and closing it
        # instead of the panel would leave the picker on top.
        self.close_page()
        self._task = asyncio.create_task(self._switch_session(session_id))

    async def _switch_session(self, session_id: str) -> None:
        """Resume a session as a task, holding the busy flag the way a command does."""
        self._activity = Activity.RUNNING
        self._note = f"resume {ELLIPSIS}"
        self._set_busy(True)
        self.app.invalidate()
        try:
            await self.resume_session(session_id)
        except COMMAND_ERRORS as error:
            self.transcript.error(str(error))
        else:
            self.notify(f"using session {session_id[:8]}", level="success")
        finally:
            self._set_busy(False)
            self._activity = Activity.READY
            self._note = None
            self.app.invalidate()
            self._start_next_command()

    async def resume_session(self, session_id: str) -> None:
        """Restore a session without holding the event loop for the work.

        The reading, the parsing, and the building of rows — and the first
        measuring of those rows at the width the view has now — happen on a worker
        thread; what is left for the loop is the assignment that makes the result
        the visible conversation. While it runs the interface keeps drawing and
        taking keys, which a resume that parsed the file in the handler did not.
        """
        stored = await asyncio.to_thread(self._load_session, session_id)
        self._install_session(stored)

    async def fork_session(self) -> str:
        """Carry this conversation into a new session, behind the interface.

        Writing the copy is file work over everything the conversation carries, so it
        runs on a worker like a resume does, under the same busy flag: the reader keeps
        their keys, another command is refused, and the status line says what is
        happening while the fork is written. The new session is then installed the way
        a resumed one is, so being in a fork is like being in anything else.
        """
        # The session being left, named before it is left: the notice says where the
        # reader came from, which is only knowable here.
        previous_id, previous_title = self.client.session.id, self.client.session.title
        self._activity = Activity.RUNNING
        self._note = f"fork {ELLIPSIS}"
        self._set_busy(True)
        self.app.invalidate()
        try:
            forked = await self.client.session.fork()
            loaded = await asyncio.to_thread(self._load_session, forked.id)
        finally:
            self._set_busy(False)
            self._activity = Activity.READY
            self._note = None
            self.app.invalidate()
        self._install_session(loaded)
        # After the install, never before: installing replaces every entry with the
        # fork's own rows, so a line written first would be wiped by the very thing it
        # is there to describe.
        stored = loaded.stored
        self.transcript.notice(fork_notice(stored.id, stored.title, previous_id, previous_title, self.client.workspace))
        return stored.id

    def restore_session(self, session_id: str, *, window: Callable[[], tuple[int, Theme]] | None = None) -> None:
        """Replace the visible history with the chosen persisted branch.

        The same two steps :meth:`resume_session` takes, run where the caller is:
        the command line calls this on its own worker thread, before the interface
        has a loop to hold up.

        Args:
            session_id: The session to restore.
            window: Where the rows will be drawn — the width and the palette — when
                this view is not laid out yet, which is the case on the command
                line: the real tree is built behind a frame painted by another
                app, so ``self.view`` has no size to measure at. It is a function,
                called once the file has been read, because the terminal's size and
                the palette it asked for are settled by then and may not have been
                when the call was made.
        """
        self._install_session(self._load_session(session_id, window=window))

    def _load_session(self, session_id: str, *, window: Callable[[], tuple[int, Theme]] | None = None) -> LoadedSession:
        """Read a session and prepare its rows, changing nothing the shell shows.

        Safe to run on a worker thread: the rows live in a transcript of their own
        until they are installed, so nothing here is visible to the loop. The
        blocks are measured now, at the width and palette they will be drawn in, so
        the loop's first look at them is a cache hit; a window that has since
        changed size simply misses and measures again, as it would have.

        A view that is not laid out reports a width of one column, and measuring
        every row at one column is the most expensive thing the transcript can be
        asked and is no use to anyone: it is what this did before it was told where
        the rows would go, and the first frame then measured them all again.
        """
        with collector_paused():
            stored = self.client.sessions.read_blocking(session_id)
            transcript = self.transcript
            replayed = replay(
                stored.records,
                renderers=transcript.renderers,
                presenters=transcript.presenters,
                frame=transcript.frame,
                max_entries=transcript.max_entries,
            )
            rows = replayed.transcript
            width, theme = window() if window is not None else (self.view.line_width, self.view.theme)
            for entry in rows.entries:
                block_for(entry, width, theme, rows.frame, presenters=rows.presenters).count(width)
        return LoadedSession(stored, replayed)

    def _install_session(self, loaded: LoadedSession) -> None:
        """Make a loaded session the visible one. Assignment only; runs on the loop."""
        previous = self.agent.active_model
        self.transcript.replace(loaded.replayed.transcript.entries)
        self.client.sessions.install(loaded.stored)
        if not self.transcript.entries:
            self.transcript.welcome(WELCOME)
        self._announce_restored_model(previous, loaded.stored)
        self.view.follow_tail = True
        self.view.clear_selection()
        self._session_title = loaded.stored.title
        self._sync_lock()
        self._usage = self.client.usage
        self._refresh_tasks()
        # The held follow-ups continued the conversation being left; they are handed back
        # as text, after the new transcript is up so the line that says so is in it.
        self._return_follow_ups_to_draft()
        self.app.request_layout()

    def _announce_restored_model(self, previous: ModelConfig, stored: StoredSession) -> None:
        """Say so when resuming a session moved the model, or could not.

        The model is part of what the reader picks up when they come back to a session, and a
        header that quietly shows another name is not a thing to notice. Silence is for when
        nothing changed: the session never recorded a model, or it is the one already in use.
        """
        current = self.agent.active_model
        if current is not previous:
            self.transcript.announce(f"Model set to {current.shown_name}, the one this session last used.")
        elif stored.model and self.agent.find_model(stored.model) is None:
            self.transcript.notice(
                f"This session last used {stored.model}, which is not in your configuration; "
                f"staying on {current.shown_name}."
            )

    def _remeasure_context_later(self) -> None:
        """Measure the context again, for a figure that cannot be true.

        Only a billed size at or past the window is replaced this way: a request
        cannot be larger than the window it is measured against, so the
        measurement of the request this process assembled is the better answer.
        A *restored* session is deliberately not measured here: its stored usage
        is the provider's count of a real request, while a list rebuilt from the
        store still holds messages the live request no longer carries — counting
        those measured 1.65 M tokens against a provider's 326 k, which is how the
        share came to sit at a hundred.

        Nothing happens where no loop can carry it, since the command line builds
        the application on a worker thread that has none; this figure is only ever
        replaced while the interface is up.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._measure_task is not None and not self._measure_task.done():
            self._measure_task.cancel()
        self._measure_task = loop.create_task(self._remeasure_context())

    async def _remeasure_context(self) -> None:
        """Seed the status line's context figure with the measured request."""
        report = await self.client.session.context()
        if report is None:
            return
        self._usage = replace(self._usage, context_tokens=report.used)
        self.app.request_layout()

    def _remember_session_title(self) -> None:
        """Cache the active session's title, which the status line paints per frame."""
        self._session_title = self.client.session.title
        self._sync_messaging()

    def _title_session_later(self, session_id: str) -> None:
        """Ask the agent to name a session once, off the composer's critical path."""
        if self._title_task is not None and not self._title_task.done():
            return
        self._title_task = asyncio.create_task(self._name_session(session_id))

    async def _name_session(self, session_id: str) -> None:
        """Store the title the agent summarizes and show it in the status line."""
        try:
            if session_id != self.client.session.id:
                return  # the reader moved on; naming it from here would switch back to it
            title = await self.client.session.name_it()
        except Exception:
            return  # naming a session is a nicety; never report its failure
        if title is None:
            return
        if session_id == self.client.session.id:
            self._session_title = title
            self._sync_messaging()
            self.app.invalidate()

    async def _stop_title_task(self) -> None:
        """Stop a title request that is still in flight when the app exits."""
        if self._title_task is None or self._title_task.done():
            return
        self._title_task.cancel()
        await asyncio.gather(self._title_task, return_exceptions=True)


def fork_notice(
    session_id: str,
    title: str | None,
    previous_id: str,
    previous_title: str | None,
    workspace: Path,
) -> str:
    """Return what a fork leaves in the conversation: which two sessions, and how to reach either.

    A fork is the one command that moves the reader without their asking to go
    anywhere, so it says where they are *and* where they were: the session they left
    is where the work that led here lives, and it is one `/resume` away. The command
    line is named too, because it is the form that still works from another directory
    later — the store is keyed by workspace, so an id on its own means nothing in
    another checkout, and its line carries a placeholder rather than one of the two
    ids, since either fits.

    One command to a line: the transcript wraps at its column budget, and a hard wrap
    in the middle of `--resume` reads as a typo. Each line opens with the part that
    matters, so a path too long for the window wraps where it costs least.
    """
    here = f'"{title}" {SEPARATOR} ' if title else ""
    there = f' {SEPARATOR} "{previous_title}"' if previous_title else ""
    return (
        f"Forked into a new session: {here}{session_id}\n"
        f"resume this session: /resume {session_id}\n"
        f"back to the previous session: /resume {previous_id}{there}\n"
        f"from a shell: zettcode --resume <session id> --workspace {workspace}"
    )
