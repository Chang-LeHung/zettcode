"""A request's life in the transcript: the reader's message, the wait row, the clock.

A turn is one request: the reader's message goes in, the pinned wait row opens and
counts for as long as the model is working, and when the request ends the row is
settled with the line it ended on and anything it left running is closed. The
animation step belongs here too, because it is the wait row's clock that it moves.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeGuard

from ..entries import Entry, EntryKind, EntryStatus, TextEntry, ThinkingEntry, TimedEntry, ToolEntry, WaitEntry
from ..rows import ANIMATION_SECONDS, PROCESSING
from .log import EntryLog


class TurnMixin(EntryLog):
    """Open, advance, and settle the rows that say a request is in flight."""

    #: Time source for row durations; set by :class:`~.Transcript`.
    clock: Callable[[], float]
    #: The animation step the clock is at, which the presenters pace themselves by.
    frame: int

    @staticmethod
    def _is_open_row(entry: Entry) -> TypeGuard[ThinkingEntry | ToolEntry]:
        """Return whether an entry is a reasoning or tool row that is still running.

        These are the rows a request leaves open when it ends mid-call, and the
        ones a new wait row must not be opened beside. The wait row itself is not
        one of them: it is settled by the request's end, with the line it ended on.
        """
        return isinstance(entry, (ThinkingEntry, ToolEntry)) and entry.running

    def user_message(self, text: str, *, side: bool = False) -> None:
        """Append a historical user message without opening a live wait row.

        Args:
            text: What the reader asked.
            side: The message was a side question, which the row shows as such.
        """
        self._add(TextEntry(id=self._next_id, kind=EntryKind.USER, text=text, side=side))

    def begin_turn(self, prompt: str, *, side: bool = False) -> None:
        """Record the user prompt and open the first wait row for the reply.

        Args:
            prompt: What the reader asked, as it should appear in the transcript.
            side: The question is a side one: answered here, never part of the
                conversation the model carries afterwards.
        """
        self.user_message(prompt, side=side)
        self.wait_for_model()

    def wait_for_model(self) -> bool:
        """Open the pinned wait row for a request, and report whether it opened.

        Nothing is known about the response yet, and a call can take seconds, so
        the row goes up as soon as the request starts and stays for all of it:
        the loop calls the model again after every tool batch, and one row that
        has been counting the whole time says more than a row per batch would.
        """
        if self._open_wait() is not None:
            return False
        # A row an interrupted request left running is one more reason not to
        # open a second: the transcript already says work is in progress, and
        # the animation walks only the rows a request opens, so a stray row
        # behind that range would never be brought up. The request's own end
        # closes them (:meth:`finish_running_rows`), which is what keeps the
        # range the whole truth; this is the backstop that depends on it.
        if any(self._is_open_row(entry) for entry in self.entries):
            return False
        self._turn_from = len(self.entries)
        self._add(WaitEntry(id=self._next_id, title=PROCESSING, started_at=self.clock()))
        return True

    def settle_wait(self, text: str) -> bool:
        """Close the pinned wait row with the line its request ended on.

        The row is what the reader watched for the whole request, so it is where
        the outcome belongs: it keeps its place at the bottom of the transcript
        and its own timer becomes the elapsed time it reports. A row left running
        — or removed, as one used to be as soon as the answer started — is how a
        stopped request reads as one that said nothing at all.

        Args:
            text: The line to leave in its place, such as
                ``Processed for 12s · 22:53``.
        """
        row = self._open_wait()
        if row is None:
            return False
        row.text = text
        row.finish(EntryStatus.COMPLETED, self.clock())
        self._changed(row)
        return True

    def finish_restored_tools(self) -> None:
        """Mark tool calls without stored results as interrupted, not running."""
        self.finish_running_rows("Result unavailable (session interrupted)")

    def finish_running_rows(self, note: str) -> None:
        """Close every row a finished run left open, and say why.

        A request that ends mid-call — stopped, failed, or restored from a
        session whose turn never completed — leaves rows whose result will never
        arrive. They keep their own timer up to the moment the request ended and
        are marked skipped, so the transcript holds no row that still claims to
        be working after nothing is. The wait row is not one of them: the shell
        settles that one with the line the request ended on.

        Args:
            note: What the body of an unfinished tool row is replaced with.
        """
        changed = False
        for index, entry in enumerate(self.entries):
            if not self._is_open_row(entry):
                continue
            if isinstance(entry, ToolEntry) and not entry.text:
                entry.text = note
            entry.finish(EntryStatus.SKIPPED, self.clock())
            self._touch(index)
            changed = True
        if changed:
            self.version += 1

    def advance_frame(self) -> None:
        """Move the activity animation on, and bring every running timer up.

        The waiting row is the one row that sweeps; a reasoning or tool row
        above it is painted flat, so a step rebuilds it only because its timer
        moved.

        The walk covers the request's own rows and no more: a row that is not a
        row at all can sit between two running ones — an approval or a command
        notice lands beside the call it answered, and a batch's results can
        arrive out of order — so every running row in the range is brought up,
        and the range bounds the cost instead of the length of the session.

        The counter is derived from the clock, one step per
        :data:`ANIMATION_SECONDS`, rather than counted in terminal ticks: the
        presenters pace their sweep and blink with it, so a terminal repainting
        ten times a second and one repainting sixty times a second look the
        same. A tick that falls inside the step it already sits on changes
        nothing, and says so: every version bump makes the transcript view
        measure every entry again, so the frame rate a busy shell paints at
        must not decide how much work that is.
        """
        frame = int(self.clock() / ANIMATION_SECONDS)
        if frame == self.frame:
            return
        self.frame = frame
        changed = False
        for index in range(self._turn_from, len(self.entries)):
            entry = self.entries[index]
            if not isinstance(entry, TimedEntry) or not entry.running:
                continue
            entry.tick(self.clock())
            self._touch(index)
            changed = True
        if changed:
            self.version += 1
