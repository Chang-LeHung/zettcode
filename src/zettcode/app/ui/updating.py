"""The background release check, and the panel that offers what it found.

The check is deliberately not part of the start: it is a task started beside the
first frame, and the panel is drawn from the *file* the last check left, so a
start never waits on the network to decide what to paint.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

from ... import __version__
from ...tui import Screen
from ...update import (
    UpdateState,
    check_for_update,
    installed_version,
    is_newer,
    read_state,
    record_install,
    run_upgrade,
    running_from,
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
        path = self.agent.runtime.config.update_file
        state = read_state(path)
        shadow = state.shadowed_by(__version__)
        if shadow is not None:
            self._explain_shadow(state, shadow, path)
            return None
        latest = state.offer(__version__)
        if latest is None:
            return None
        command = upgrade_command()
        page = UpdatePage(latest, __version__, command, on_choice=lambda choice: self._answer_update(choice, latest))
        self.app.push_screen(Screen(bottom_panel(page, rows=UPDATE_ROWS), name=PAGE_SCREEN, modal=True))
        self.app.request_layout()
        return state

    def _explain_shadow(self, state: UpdateState, installed: str, path: Path) -> None:
        """Say, once, that an upgrade worked but is not what is running, instead of offering it again.

        Offering the upgrade a second time would change nothing — it is installed — and would look
        exactly like an upgrade that never happened. What is useful is where the running code is
        coming from. The explanation is recorded as given, so the next start is quiet about it.
        """
        if state.noted == installed:
            return
        self.transcript.notice(
            f"ZettCode {installed} is installed, but this session runs {__version__} from {running_from()}: "
            "something else is supplying the code (an editable checkout, PYTHONPATH?), so upgrading again "
            "would not change it"
        )
        try:
            write_state(replace(state, noted=installed), path)
        except OSError:
            pass  # said again next start, which is the right failure for a note

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
        """Install the newer release in the background, check that it is there, and report which.

        A package manager exiting 0 is not an upgrade: ``uv tool upgrade`` answers "Nothing to
        upgrade" with 0, and a pip whose index has not listed the release yet answers "already
        satisfied" with 0. So the version is read back from the interpreter that was upgraded, and
        only that is believed: it is what the notice says, and it is what is written to the file the
        next start reads. An upgrade that left the old version is reported as that, with the way to
        try again, and writes nothing, so it is offered again.

        The running process keeps the code it started with, so the notice says what the reader has
        to do about it — restart — rather than implying the window is already the new version.
        """
        command = upgrade_command()
        ok, output = await run_upgrade(command)
        if not ok:
            reason = output.splitlines()[-1] if output else "no output"
            self.transcript.error(f"upgrade failed: {reason}")
            self.transcript.notice(f"run it yourself: {' '.join(command)}")
            return
        installed = await installed_version()
        if installed is None:
            self.transcript.notice(
                f"the upgrade ran, but the installed version could not be read back — restart and check "
                f"with `zettcode --version`; if it is not {latest}: {' '.join(command)}"
            )
            return
        if is_newer(latest, installed):
            self.transcript.error(f"the upgrade ran, but ZettCode is still {installed}, not {latest}")
            self.transcript.notice(
                f"the package index may not list {latest} yet; try again in a few minutes: {' '.join(command)}"
            )
            return
        try:
            record_install(self.agent.runtime.config.update_file, installed)
        except OSError:
            pass  # the install happened; failing to write it down must not make it look as if it had not
        self.transcript.notice(f"ZettCode {installed} installed — restart to use it")
        self.notify("upgrade finished", level="success")

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
