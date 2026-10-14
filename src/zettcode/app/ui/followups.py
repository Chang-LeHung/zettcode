"""Messages typed while the agent is working: steer them in, or hold them as follow-ups.

A reader who types during a request means one of two things. Either "change what you are
doing" — a steering message, which the agent adopts at its next model or tool boundary and
which replaces the rest of the task — or "when you are done, also do this" — a follow-up,
which waits and goes out as a turn of its own. The shell asks which, because nothing in the
text says.

The two differ in who holds the message. A steering message is handed to the agent the moment
it is sent and cannot be taken back; a follow-up stays here, so it is the one that can be
selected, edited, and put in a different order. That is why this module owns the follow-up
list and the keys that work on it, and why the steering list stays a plain display.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ...tui import Screen
from ...tui.render import truncate
from ..agent.agent.prompt import PromptPart, carries_image, mention_hint
from .shell import MAX_FOLLOW_UPS, MAX_STEERING, PAGE_SCREEN, ShellState
from .widgets import SEND_KIND_ROWS, SendKind, SendKindPage, bottom_panel
from .widgets.follow_up import one_line

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from collections.abc import Sequence


@dataclass(frozen=True, slots=True)
class FollowUp:
    """One message waiting for the request to end.

    Attributes:
        text: The message as the reader wrote it, pasted text put back; what the row
            shows and what editing it returns to the composer.
        parts: The same message as the ordered parts of a turn, taken when it was sent so
            an ``@`` reference is read the way it was typed.
    """

    text: str
    parts: tuple[PromptPart, ...]


class FollowUpsMixin(ShellState):
    """Ask what a message sent mid-request is, hold the follow-ups, and send them in turn."""

    # -- a message typed while busy ---------------------------------------------------
    def _send_while_busy(self, value: str) -> bool:
        """Decide what one plain message typed during a request becomes.

        When it could be either kind the reader is asked, and the draft stays in the
        composer meanwhile — which is why this answers ``False`` then: the draft is only
        cleared once there is an answer. When only one kind is possible there is nothing to
        ask, and a reader who could not steer is told why only if the reason is not obvious.

        Returns:
            What :meth:`submit` returns: whether the draft was taken.
        """
        parts = self.composer.parts()
        if self._editing_slot is not None:
            # A message taken out to be edited goes back where it was, as what it was.
            return self._queue_follow_up(value, parts, slot=self._editing_slot)
        blocked = self._steer_blocked()
        if blocked is None:
            self._ask_send_kind(value, parts)
            return False
        if blocked:
            self.transcript.notice(f"queued as a follow-up \u2014 {blocked}")
        return self._queue_follow_up(value, parts)

    def _steer_blocked(self) -> str | None:
        """Return why the running work cannot be steered, or ``None`` when it can.

        An empty string means there is nothing to steer — a command is running, not a
        turn, and a ``/btw`` question is one of those — which needs no explaining; any other
        text is shown to the reader.
        """
        if not self._turn_running:
            return ""
        if self._steering_sent >= MAX_STEERING:
            return f"steering limit reached ({MAX_STEERING})"
        return None

    def _ask_send_kind(self, value: str, parts: Sequence[PromptPart]) -> None:
        """Put the question on screen; its answer comes back through :meth:`_kind_chosen`."""
        page = SendKindPage(
            value,
            on_choice=lambda kind: self._kind_chosen(kind, value, parts),
            on_cancel=self.close_page,
        )
        self.app.push_screen(Screen(bottom_panel(page, rows=SEND_KIND_ROWS), name=PAGE_SCREEN, modal=True))
        self.app.invalidate()

    def _kind_chosen(self, kind: SendKind, value: str, parts: Sequence[PromptPart]) -> None:
        """Carry out the answer, then clear the draft it was about.

        The request may have ended while the question was open, so the state is read again
        rather than trusted: with nothing running there is nothing to steer or to follow, and
        the message is simply sent.
        """
        self.close_page()
        if not self._busy:
            self.submit(value)
            self.composer.commit(value)
            return
        if kind is SendKind.STEER:
            if self._steer_now(value, parts):
                self.composer.commit(value)
            else:
                self._refuse_busy()
            return
        if self._queue_follow_up(value, parts):
            self.composer.commit(value)

    def _steer_now(self, value: str, parts: Sequence[PromptPart]) -> bool:
        """Hand one message to the running request as steering, and show it waiting to be adopted.

        Text goes as it was typed. A message with pictures is built the way a turn is, and the agent
        reports it by the text *that* has, which is what the queue must match.

        Returns:
            Whether the agent took it; ``False`` leaves everything as it was.
        """
        message = self.agent.turn(parts) if carries_image(parts) else value
        key = message if isinstance(message, str) else message.text
        if self._steer_blocked() is None and self.agent.steer(message):
            self._queue_steering(value, key, parts)
            return True
        return False

    def _steer_follow_up(self) -> bool:
        """Turn the highlighted follow-up into a steering message, without taking it out of the reader's hands first.

        A follow-up waits for the request to finish; steering changes what the request does *now*,
        so this is for the message that turned out to be urgent. It is the same hand-over the
        question makes, and it is refused for the same reasons, said in words: nothing is running
        (the list is held after a stop, and steering has nothing to steer), a command is running
        rather than a turn, or the steering limit is reached. A refused message stays where it is.

        Returns:
            Whether it was sent. The key is always consumed; the reason, when there is one, is flashed.
        """
        index = self._follow_up_selected
        if index is None or index >= len(self._follow_ups):
            return False
        if not self._busy:
            self.flash("nothing is running to steer \u2014 it will be sent when you send your next message")
            return False
        blocked = self._steer_blocked()
        if blocked is not None:
            self.flash(blocked or "only a reply can be steered, not a command")
            return False
        item = self._follow_ups[index]
        if not self._steer_now(item.text, item.parts):
            self._refuse_busy()
            return False
        del self._follow_ups[index]
        if self._editing_slot is not None and index < self._editing_slot:
            self._editing_slot -= 1
        remaining = len(self._follow_ups)
        self._follow_up_selected = None if not remaining else min(index, remaining - 1)
        self._sync_follow_ups()
        self.flash(f"steering: {truncate(one_line(item.text), 40)}", level="success")
        return True

    # -- the follow-up list ------------------------------------------------------------
    def _queue_follow_up(self, value: str, parts: Sequence[PromptPart], *, slot: int | None = None) -> bool:
        """Hold one message until the request ends.

        Args:
            value: The message, pasted text put back.
            parts: The message as the parts of a turn.
            slot: Where in the list it goes; ``None`` is the end. A message taken out to be
                edited goes back to the slot it left.

        Returns:
            Whether it was taken; ``False`` leaves the draft where it is.
        """
        if len(self._follow_ups) >= MAX_FOLLOW_UPS:
            self.transcript.error(f"follow-up limit reached ({MAX_FOLLOW_UPS}) \u2014 wait for the queue to drain")
            self.app.invalidate()
            return False
        item = FollowUp(value, tuple(parts))
        if slot is None:
            self._follow_ups.append(item)
        else:
            self._follow_ups.insert(min(slot, len(self._follow_ups)), item)
        self._editing_slot = None
        self._sync_follow_ups()
        return True

    def _sync_follow_ups(self) -> None:
        """Show the list and the highlight as they are, making room for them if they changed."""
        if not self._follow_ups:
            self._follow_ups_held = False  # nothing left to hold
        changed = self.follow_ups.set_messages(
            [item.text for item in self._follow_ups],
            self._follow_up_selected,
            held=not self._busy,
        )
        if changed:
            self.app.request_layout()
        self.app.invalidate()

    @property
    def _follow_up_selecting(self) -> bool:
        """Return whether a follow-up is highlighted."""
        return self._follow_up_selected is not None

    def _select_follow_up(self, step: int) -> None:
        """Move the highlight one row, entering the list from the composer's side.

        From nothing, going up lands on the row nearest the composer and going down on the
        first. Going down from the last row leaves the list — the highlight goes back to the
        composer — and going up from the first stays on it.
        """
        count = len(self._follow_ups)
        if not count:
            return
        current = self._follow_up_selected
        if current is None:
            target: int | None = count - 1 if step < 0 else 0
        else:
            target = current + step
            target = None if target >= count else max(0, target)
        self._follow_up_selected = target
        self._sync_follow_ups()

    def _deselect_follow_up(self) -> None:
        """Take the highlight off, leaving the list as it is."""
        if self._follow_up_selected is None:
            return
        self._follow_up_selected = None
        self._sync_follow_ups()

    def _move_follow_up(self, step: int) -> None:
        """Swap the highlighted message with its neighbour, keeping it highlighted."""
        index = self._follow_up_selected
        if index is None:
            return
        target = index + step
        if not 0 <= target < len(self._follow_ups):
            return
        self._follow_ups[index], self._follow_ups[target] = self._follow_ups[target], self._follow_ups[index]
        self._follow_up_selected = target
        self._sync_follow_ups()

    def _delete_follow_up(self) -> None:
        """Remove the highlighted message from the list; it will not be sent.

        The highlight stays where the reader is: on the message that moved up into the
        place, or on the one before it when the last row went, and nowhere when the list is
        empty. The row that went is named in the line above the composer, because a key as
        close to the hand as Backspace should say what it just did.
        """
        index = self._follow_up_selected
        if index is None:
            return
        removed = self._follow_ups.pop(index)
        if self._editing_slot is not None and index < self._editing_slot:
            self._editing_slot -= 1
        remaining = len(self._follow_ups)
        self._follow_up_selected = None if not remaining else min(index, remaining - 1)
        self._sync_follow_ups()
        self.flash(f"removed follow-up: {truncate(one_line(removed.text), 40)}", level="success")

    def _edit_follow_up(self) -> bool:
        """Take the highlighted message out of the list and put it in the composer.

        Sending it again puts it back in the slot it left, so editing a message in the middle
        of the list does not move it to the end. A draft already in the composer is not
        overwritten: the reader is told to deal with it first.

        Returns:
            Whether the message was taken out.
        """
        index = self._follow_up_selected
        if index is None:
            return False
        if self.composer.text.strip():
            self.flash("finish or clear the draft (Ctrl-C) before editing a queued message")
            return True
        item = self._follow_ups.pop(index)
        self._follow_up_selected = None
        self._editing_slot = index
        self._sync_follow_ups()
        self.composer.restore(item.parts)
        self.app.request_layout()
        return True

    def _composer_changed(self) -> None:
        """React to the draft changing: refresh the menu, and let go of what it no longer means.

        Typing means the reader has moved on from the highlighted message, so the highlight
        goes; and an emptied draft means a message taken out for editing was abandoned.
        """
        # A key was pressed: nothing may pause the screen the reader is typing into.
        self.collector.typed()
        self._refresh_completions()
        if self._follow_up_selected is not None:
            self._deselect_follow_up()
        if self._editing_slot is not None and not self.composer.text:
            self._editing_slot = None

    # -- when a request ends -----------------------------------------------------------
    def _settle_queues(self, completed: bool, *, turn: bool) -> None:
        """Decide what the waiting messages become now that the request is over.

        The follow-ups are the reader's own list, kept by this shell, and they are attached
        only to a conversation that *ended well*: a request that was stopped or failed does
        not send them and does not give them up either. They stay where they are, the reader
        types whatever they meant to say instead, and when that reply completes they go out
        behind it. So Escape is only ever "stop this" — it never costs the reader their list.

        What does not survive is a steering message the agent never read. It was written to
        redirect the request that just ended, nobody is going to read it, and it is text the
        reader typed a moment ago, so it goes back into the draft rather than being dropped.

        Whether the list is *held* is a state, not a property of the thing that just ended:
        a stop with follow-ups waiting holds it, and only a reply completing releases it. A
        command that finishes in between — a ``/btw`` question, which is not part of the
        conversation at all — leaves it as it was.

        Args:
            completed: Whether the request ended by answering.
            turn: Whether it was a turn of the conversation, as opposed to a command.
        """
        # Each with the parts it was sent as, so a picture is not lost on the way back.
        unread = [
            (value, (self._steering_meta[index][1] if index < len(self._steering_meta) else ()) or (value,))
            for index, value in enumerate(self._steering)
        ]
        self._clear_steering()
        if completed and turn:
            self._follow_ups_held = False
        if completed:
            # A request that answered normally with one still unread hands it on, ahead of
            # the follow-ups: it was sent first.
            if unread:
                self._follow_ups[:0] = [FollowUp(text, tuple(parts)) for text, parts in unread]
                self._sync_follow_ups()
            return
        if unread:
            noun = "steering message was" if len(unread) == 1 else "steering messages were"
            self._return_to_draft(
                unread,
                f"{len(unread)} {noun} never read by the agent and {'is' if len(unread) == 1 else 'are'} back in the draft",
            )
        if self._follow_ups:
            self._follow_ups_held = True
            held = len(self._follow_ups)
            noun = "follow-up is" if held == 1 else "follow-ups are"
            self.transcript.notice(f"{held} {noun} held and will be sent after your next reply completes")

    def _return_to_draft(self, items: Sequence[tuple[str, Sequence[PromptPart]]], notice: str) -> None:
        """Put messages back in the composer, after whatever is already there, and say so.

        Args:
            items: Each message as its text and the parts it was sent as.
            notice: The line to leave in the transcript.
        """
        draft = self.composer.text.strip()
        pictures = self.composer.images or any(carries_image(parts) for _, parts in items)
        if pictures:
            # With a picture in play the draft is rebuilt from parts, so each picture is a chip
            # again and keeps its place; the labels are renumbered across the whole draft.
            merged: list[PromptPart] = list(self.composer.parts()) if draft else []
            for index, (_, parts) in enumerate(items):
                if merged or index:
                    merged.append("\n\n")
                merged.extend(parts)
            self.composer.restore(merged)
        else:
            self.composer.position = len(self.composer.text)
            self.composer.paste(("\n\n" if draft else "") + "\n\n".join(text for text, _ in items))
        self.transcript.notice(notice)
        self.app.request_layout()

    def _return_follow_ups_to_draft(self) -> None:
        """Give the held follow-ups back to the reader, because their conversation is over.

        They continue one conversation, so they cannot go on into another: a new session, a
        resumed one, and a fork all end the list. Handing them back as text keeps what the
        reader wrote; sending them into a conversation they were not written for would not.
        """
        if not self._follow_ups:
            return
        texts = [item.text for item in self._follow_ups]
        items = [(item.text, item.parts) for item in self._follow_ups]
        self._follow_ups.clear()
        self._follow_up_selected = None
        self._editing_slot = None
        self._sync_follow_ups()
        noun = "held follow-up" if len(texts) == 1 else "held follow-ups"
        self._return_to_draft(
            items,
            f"{len(texts)} {noun} from the previous session {'is' if len(texts) == 1 else 'are'} back in the draft",
        )

    def _start_follow_up(self) -> None:
        """Send the first waiting message as a turn of its own."""
        item = self._follow_ups.pop(0)
        if self._follow_up_selected is not None:
            self._follow_up_selected = None if self._follow_up_selected == 0 else self._follow_up_selected - 1
        if self._editing_slot:
            self._editing_slot -= 1
        self._sync_follow_ups()
        # Busy before the task has run: between here and its first step a keystroke must not
        # be able to start a second turn beside it.
        self._set_busy(True)
        self._task = asyncio.create_task(
            self._run_prompt(item.text, item.parts, mention_hint(item.parts, self.mentions))
        )
