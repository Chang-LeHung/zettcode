"""A request's life in the transcript: the reader's message, the wait row, the clock.

A turn is one request: the reader's message goes in, the pinned wait row opens and
counts for as long as the model is working, and when the request ends the row is
settled with the line it ended on and anything it left running is closed. The
animation step belongs here too, because it is the wait row's clock that it moves.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import PurePath
from typing import TypeGuard

from .....tui.render import display_width
from ...dialogue.relay import VIA_EXTERNAL, Relayed
from ..changes import changed_files
from ..entries import (
    ChangesEntry,
    Entry,
    EntryKind,
    EntryStatus,
    RelayEntry,
    TextEntry,
    ThinkingEntry,
    TimedEntry,
    ToolEntry,
    WaitEntry,
)
from ..pulse import ANIMATION_SECONDS, blink_state, wait_picture
from ..text import PROCESSING, duration_text, elapsed_text, quiet_text
from ..tips import TipDeck
from .log import EntryLog


class TurnMixin(EntryLog):
    """Open, advance, and settle the rows that say a request is in flight."""

    #: Time source for row durations; set by :class:`~.Transcript`.
    clock: Callable[[], float]
    #: The animation step the clock is at, which the presenters pace themselves by.
    frame: int
    #: What the last animation step that was taken drew; see :meth:`advance_frame`.
    _picture_drawn: tuple[object, ...] | None
    #: Where the tips under the waiting row come from; set by :class:`~.Transcript`.
    tip_deck: TipDeck | None

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

    def relayed_message(self, relayed: Relayed) -> None:
        """Append a message another session sent, without opening a wait row."""
        self._add(
            RelayEntry(
                id=self._next_id,
                peer=relayed.sender,
                text=relayed.text,
                outgoing=False,
                by_agent=relayed.by_agent,
                external=relayed.via == VIA_EXTERNAL,
            )
        )

    def sent_message(self, peer: str, text: str, note: str = "") -> None:
        """Append a message this session's reader sent to another session.

        Args:
            peer: The handle it was sent to.
            text: What was sent.
            note: What became of it, such as ``started`` or ``queued``.
        """
        self._add(RelayEntry(id=self._next_id, peer=peer, text=text, outgoing=True, by_agent=False, note=note))

    def begin_turn(self, prompt: str, *, side: bool = False, relayed: Relayed | None = None) -> None:
        """Record the user prompt and open the first wait row for the reply.

        Args:
            prompt: What the reader asked, as it should appear in the transcript.
            side: The question is a side one: answered here, never part of the
                conversation the model carries afterwards.
            relayed: The turn answers a message from another session, which is drawn as that
                and not as something the reader typed.
        """
        if relayed is not None:
            self.relayed_message(relayed)
        else:
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
        tips = self.tip_deck.next() if self.tip_deck is not None else ()
        self._add(WaitEntry(id=self._next_id, title=PROCESSING, started_at=self.clock(), tips=tips))
        return True

    def summarize_changes(self, workspace: PurePath | None = None) -> bool:
        """Say which files the request changed, above the pinned row; say nothing when it changed none.

        Called as the request ends, before the wait row is settled, so the line that says how long it
        ran stays the last one. It covers the rows of this request only, and counts only calls that
        succeeded.

        Args:
            workspace: The directory paths are shown relative to.

        Returns:
            Whether a summary was added.
        """
        files = changed_files(self.entries[self._turn_from :], workspace)
        if not files:
            return False
        self._add(ChangesEntry(id=self._next_id, files=files))
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

    def advance_frame(self) -> bool:
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

        Most steps repeat the picture before them. A step is a hundred and twentieth of
        a second, but the highlight sits on a whole column and crosses a word in a
        second and a half, so it changes a few dozen times a second; the icon turns
        over twice in a second and a half; a timer shows whole seconds. A step that lands on the picture already drawn is not
        taken: the frame counter, the timers and the version stay where they were, the
        cached rows stay valid, and the caller is told nothing changed, so the loop
        can skip the frame it would have painted — the measured cost of painting every
        one was a third of a core for a reader who was only waiting.

        Returns:
            Whether anything the reader can see is different from the last step taken.
        """
        now = self.clock()
        frame = int(now / ANIMATION_SECONDS)
        if frame == self.frame:
            return False
        # One walk, which both the picture and the timers use: the rows of this request and
        # no more, so what a step reads does not grow with the session.
        running = [
            (index, entry)
            for index in range(self._turn_from, len(self.entries))
            if isinstance(entry := self.entries[index], TimedEntry) and entry.running
        ]
        self._measure_quiet(now, [entry for _, entry in running])
        picture = self._picture(frame, now, [entry for _, entry in running])
        if picture == self._picture_drawn:
            return False
        self._picture_drawn = picture
        self.frame = frame
        for index, entry in running:
            entry.tick(now)
            self._touch(index)
        if running:
            self.version += 1
        return True

    def turn_said_nothing(self) -> bool:
        """Return whether the request that has just ended produced nothing a reader could see.

        No answer, no tool, no reasoning: the model was asked and sent back an empty reply, which the stream reports
        as a request that completed. Without a line saying so the reader is left with a row that says how long it
        took and a conversation exactly as it was, which looks like the request was lost.
        """
        wanted = (EntryKind.ANSWER, EntryKind.TOOL, EntryKind.THINKING, EntryKind.MESSAGE)
        return not any(entry.kind in wanted for entry in self.entries[self._turn_from :])

    def heard(self) -> None:
        """Note that the agent just said something, which is what ends a stretch of silence.

        Called for every event the agent emits. It changes nothing a reader can see, so it moves no version.
        """
        wait = self._open_wait()
        if wait is not None:
            wait.heard_at = self.clock()

    @staticmethod
    def _measure_quiet(now: float, running: list[TimedEntry]) -> None:
        """Say how long the model has been silent, when the model is what the request is waiting for.

        A request with a tool, a reasoning row or a compaction in flight is waiting for that, not for the model,
        and a silence there is a command that takes a while: it says nothing then.
        """
        waits = [entry for entry in running if isinstance(entry, WaitEntry)]
        waiting_on_the_model = len(waits) == len(running)
        for wait in waits:
            since = wait.heard_at if wait.heard_at is not None else wait.started_at
            wait.quiet = max(0.0, now - since) if waiting_on_the_model and since is not None else 0.0

    @staticmethod
    def _picture(frame: int, now: float, running: list[TimedEntry]) -> tuple[object, ...]:
        """Return everything the running rows and the status icon would show at ``frame``.

        The waiting row's highlight and rest, the icon's state, and — for every running
        row — the text its timer reads. Equal pictures are drawn identically,
        which is what lets a step that repeats one be skipped.
        """
        shown: list[str] = []
        wait: tuple[bool, int] = (False, 0)
        for entry in running:
            if entry.started_at is not None:
                # What the row will *say*, not a number it is derived from: the wait row counts
                # whole seconds and every other row counts tenths, and a signature that rounded
                # the second to the first would freeze a tenths timer for as long as the rest of
                # the picture holds still — a second at a time, which read as 0.1 jumping to 0.9.
                elapsed = now - entry.started_at
                shown.append(elapsed_text(elapsed) if isinstance(entry, WaitEntry) else duration_text(elapsed))
            if isinstance(entry, WaitEntry):
                wait = wait_picture(frame, display_width(entry.title))
                # What the quiet clock will say, so a silence that grows is drawn as it grows and one that
                # has not reached the threshold costs nothing.
                shown.append(quiet_text(entry.quiet) or "")
        return (wait, blink_state(frame), tuple(shown))
