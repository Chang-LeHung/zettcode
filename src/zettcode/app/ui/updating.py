"""The background release check, and the panel that offers what it found.

The check is deliberately not part of the start: it is a task started beside the
first frame, and the panel is drawn from the *file* the last check left, so a
start never waits on the network to decide what to paint.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace

from ... import __version__
from ...tui import Screen
from ...update import (
    UpdateState,
    check_for_update,
    read_state,
    run_upgrade,
    upgrade_command,
    write_state,
)
from .shell import PAGE_SCREEN, UPDATE_ROWS, ShellState
from .widgets import LATER, UPGRADE, UpdatePage, bottom_panel


class UpdateMixin(ShellState):
    """Offer a newer release, once, until the reader skips it or installs it."""

    def start_update_check(self) -> asyncio.Task[None] | None:
        """Ask PyPI in the background, unless the configuration turns it off."""
        if not self.agent.runtime.config.update_enabled:
            return None
        self._update_task = asyncio.ensure_future(self._check_for_update())
        return self._update_task

    async def _check_for_update(self) -> None:
        """Refresh the stored state; a failure means "no news", never an error."""
        await check_for_update(self.agent.runtime.config.update_file)

    def offer_update(self) -> UpdateState | None:
        """Show the panel a stored newer version asks for, if there is one."""
        if not self.agent.runtime.config.update_enabled:
            return None
        state = read_state(self.agent.runtime.config.update_file)
        latest = state.offer(__version__)
        if latest is None:
            return None
        command = upgrade_command()
        page = UpdatePage(latest, __version__, command, on_choice=lambda choice: self._answer_update(choice, latest))
        self.app.push_screen(Screen(bottom_panel(page, rows=UPDATE_ROWS), name=PAGE_SCREEN, modal=True))
        self.app.request_layout()
        return state

    def _answer_update(self, choice: str, latest: str) -> None:
        """Act on the panel: upgrade, forget this version, or ask again later."""
        self.close_page()
        if choice == UPGRADE:
            self._update_task = asyncio.ensure_future(self._run_upgrade(latest))
            return
        if choice == LATER:
            # Nothing is written: the next start reads the same file and asks
            # again, which is the whole difference between this and skipping.
            return
        path = self.agent.runtime.config.update_file
        write_state(replace(read_state(path), skipped=latest), path)
        self.transcript.notice(f"skipping ZettCode {latest}: the next release will be offered")

    async def _run_upgrade(self, latest: str) -> None:
        """Install the newer release in the background and report what happened.

        The running process keeps the code it started with, so the notice says
        what the reader has to do about it — restart — rather than implying the
        window is already the new version.
        """
        command = upgrade_command()
        ok, output = await run_upgrade(command)
        if ok:
            self.transcript.notice(f"ZettCode {latest} installed — restart to use it")
            self.notify("upgrade finished", level="success")
            return
        reason = output.splitlines()[-1] if output else "no output"
        self.transcript.error(f"upgrade failed: {reason}")
        self.transcript.notice(f"run it yourself: {' '.join(command)}")

    async def _stop_update_task(self) -> None:
        """Drop a check or upgrade still in flight when the app exits.

        Nobody is left to read the answer, and the request behind it may be
        waiting on a slow index: cancelling the await is what keeps a quit from
        holding the terminal for as long as that takes.
        """
        task, self._update_task = self._update_task, None
        if task is None or task.done():
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
