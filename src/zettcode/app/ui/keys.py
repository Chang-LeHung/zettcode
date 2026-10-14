"""The shell's keys: the keymap and every binding it registers.

The bindings are the shell's input vocabulary — scroll, redraw, attach, quit,
and the completion menu — and they live together so the keymap reads as one
table. :class:`ZettCodeApp` installs them once and never touches a key again.
"""

from __future__ import annotations

from ...tui import AnyEvent, Host
from ...tui.clipboard import copy_route
from ..agent.errors import describe_error
from .clipboard import read_image
from .shell import ASK_SCREEN, PAGE_SCREEN, ShellState


class KeysMixin(ShellState):
    """Register the keymap and handle the keys the shell owns."""

    def _install_keymap(self) -> None:
        """Register the global commands and their key bindings."""
        self.app.commands.add("interrupt", self._interrupt)
        self.app.commands.add("redraw", self._redraw)
        self.app.commands.add("toggle_thinking", self._toggle_thinking)
        self.app.commands.add("scroll_up", self._scroll_up)
        self.app.commands.add("scroll_down", self._scroll_down)
        self.app.commands.add("scroll_end", self._scroll_end)
        self.app.commands.add("attach_image", self._attach_image)
        self.app.commands.add("quit", self._quit)
        self.app.commands.add("complete_next", self._complete_next)
        self.app.commands.add("complete_previous", self._complete_previous)
        self.app.commands.add("interrupt_run", self._interrupt_run)
        self.app.commands.add("complete_accept", self._complete_accept)
        self.app.commands.add("complete_dismiss", self._complete_dismiss)
        self.app.commands.add("follow_up_up", self._follow_up_up)
        self.app.commands.add("follow_up_down", self._follow_up_down)
        self.app.commands.add("follow_up_previous", self._follow_up_previous)
        self.app.commands.add("follow_up_next", self._follow_up_next)
        self.app.commands.add("follow_up_edit", self._follow_up_edit)
        self.app.commands.add("follow_up_delete", self._follow_up_delete)
        self.app.commands.add("follow_up_steer", self._follow_up_steer)
        self.app.commands.add("follow_up_done", self._follow_up_done)
        self.app.keymap.bind("ctrl_c", "interrupt", priority="capture")
        self.app.keymap.bind("ctrl_l", "redraw", priority="capture")
        self.app.keymap.bind("ctrl_t", "toggle_thinking", priority="capture")
        # Capture priority is what lets the predicate win: the composer would
        # otherwise swallow Ctrl-D as "delete forward" even on an empty draft.
        self.app.keymap.bind(
            "ctrl_d",
            "quit",
            priority="capture",
            when=lambda: self.app.screens.top.name != PAGE_SCREEN and not self._busy and not self.composer.text,
        )
        # The follow-up list. The modifier key (Option on a Mac) is the list's own: with
        # nothing highlighted it walks into the list from the composer's side, and with a
        # message highlighted it moves that message. VS Code's terminal rewrites Option-Up and
        # Option-Down before the terminal sees them — it has a keybinding that sends the bytes of
        # Ctrl-Up and Ctrl-Down in their place — so the program is told Ctrl, never Alt, and
        # both spellings are the same key here. Nothing else in the program uses Ctrl with an
        # arrow, and on a Mac the system keeps Ctrl-Up for itself, so this takes nothing away.
        # The plain arrows move the highlight,
        # which they only do while one is highlighted — until then they are the composer's,
        # history and the cursor. Enter edits, Delete removes, Escape lets go. They are
        # capture bindings because the composer reads Up and Down as history and Enter as
        # send, and they come before the Escape and Enter bindings below: a highlighted
        # message is the most specific thing the reader is doing, so its keys win.
        self.app.keymap.bind("alt_up", "follow_up_up", priority="capture", when=self._follow_ups_listed)
        self.app.keymap.bind("alt_down", "follow_up_down", priority="capture", when=self._follow_ups_listed)
        self.app.keymap.bind("ctrl_up", "follow_up_up", priority="capture", when=self._follow_ups_listed)
        self.app.keymap.bind("ctrl_down", "follow_up_down", priority="capture", when=self._follow_ups_listed)
        self.app.keymap.bind("up", "follow_up_previous", priority="capture", when=self._follow_up_chosen)
        self.app.keymap.bind("down", "follow_up_next", priority="capture", when=self._follow_up_chosen)
        self.app.keymap.bind("enter", "follow_up_edit", priority="capture", when=self._follow_up_chosen)
        # Ctrl-S sends the highlighted message now, as steering. Not a letter: typing anything
        # lets go of the highlight, so a plain "s" would be the composer's. It is the editor's
        # usual "send", and the terminal's flow-control meaning of it is off in raw mode.
        self.app.keymap.bind("ctrl_s", "follow_up_steer", priority="capture", when=self._follow_up_chosen)
        # Backspace is what the key labelled "delete" sends on a Mac, and Delete is the one
        # that sends it everywhere else, so both remove the message.
        self.app.keymap.bind("backspace", "follow_up_delete", priority="capture", when=self._follow_up_chosen)
        self.app.keymap.bind("delete", "follow_up_delete", priority="capture", when=self._follow_up_chosen)
        self.app.keymap.bind("escape", "follow_up_done", priority="capture", when=self._follow_up_chosen)
        # Escape stops a running turn, above the uses below: a reader who wants the
        # request stopped should not have to remember that Ctrl-C is the key for
        # it, and a panel, a question, the menu, and a scrolled transcript keep
        # their own claim on the key first.
        self.app.keymap.bind("escape", "interrupt_run", priority="capture", when=self._escaping_a_run)
        self.app.keymap.bind("page_up", "scroll_up")
        self.app.keymap.bind("page_down", "scroll_down")
        # Escape is the keyboard twin of the transcript's return badge; capture
        # priority lets it win, because the composer would otherwise swallow Esc.
        self.app.keymap.bind("escape", "scroll_end", priority="capture", when=self._transcript_scrolled_up)
        # The terminal cannot deliver a pasted image, so this asks the desktop.
        self.app.keymap.bind("ctrl_v", "attach_image", priority="capture")
        # Capture priority is what lets the menu win the keys it needs: the
        # composer would otherwise read Up and Down as history navigation and
        # would treat Tab as its own inline completion.
        self.app.keymap.bind("down", "complete_next", priority="capture", when=self._menu_open)
        self.app.keymap.bind("up", "complete_previous", priority="capture", when=self._menu_open)
        self.app.keymap.bind("tab", "complete_accept", priority="capture", when=self._menu_open)
        self.app.keymap.bind("escape", "complete_dismiss", priority="capture", when=self._menu_open)
        self.app.keymap.bind("enter", "complete_accept", priority="capture", when=self._accept_on_enter)

    def _follow_ups_listed(self) -> bool:
        """Return whether there are follow-ups to move through, and nothing is on top of them."""
        return bool(self._follow_ups) and self.app.screens.top.name not in (PAGE_SCREEN, ASK_SCREEN)

    def _follow_up_chosen(self) -> bool:
        """Return whether a follow-up is highlighted, and nothing is on top of the list."""
        return self._follow_up_selecting and self.app.screens.top.name not in (PAGE_SCREEN, ASK_SCREEN)

    def _follow_up_up(self, event: AnyEvent, host: Host) -> bool:
        """Option-Up: send the highlighted follow-up sooner, or walk into the list to begin."""
        if self._follow_up_selecting:
            self._move_follow_up(-1)
        else:
            self._select_follow_up(-1)
        return True

    def _follow_up_down(self, event: AnyEvent, host: Host) -> bool:
        """Option-Down: send the highlighted follow-up later, or walk into the list to begin."""
        if self._follow_up_selecting:
            self._move_follow_up(1)
        else:
            self._select_follow_up(1)
        return True

    def _follow_up_previous(self, event: AnyEvent, host: Host) -> bool:
        """Highlight the previous follow-up."""
        self._select_follow_up(-1)
        return True

    def _follow_up_next(self, event: AnyEvent, host: Host) -> bool:
        """Highlight the next follow-up; past the last one the highlight leaves the list."""
        self._select_follow_up(1)
        return True

    def _follow_up_edit(self, event: AnyEvent, host: Host) -> bool:
        """Take the highlighted follow-up out of the list and into the composer."""
        return self._edit_follow_up()

    def _follow_up_steer(self, event: AnyEvent, host: Host) -> bool:
        """Send the highlighted follow-up to the running request as steering."""
        self._steer_follow_up()
        return True

    def _follow_up_delete(self, event: AnyEvent, host: Host) -> bool:
        """Remove the highlighted follow-up, so it is never sent."""
        self._delete_follow_up()
        return True

    def _follow_up_done(self, event: AnyEvent, host: Host) -> bool:
        """Let go of the highlighted follow-up."""
        self._deselect_follow_up()
        return True

    def _menu_open(self) -> bool:
        """Return whether the slash-command menu is showing."""
        return self.app.screens.top.name != PAGE_SCREEN and self.completions.visible

    def _escaping_a_run(self) -> bool:
        """Return whether Escape means "stop the request" here.

        The key has other jobs, and each of them is answered elsewhere: a panel
        and the question the model is waiting on own Escape while they are up, the
        menu asks for it to dismiss itself, a scrolled transcript takes it as
        "back to the newest line", a highlighted follow-up takes it to let go,
        and a selection belongs to Ctrl-C, which copies. What is left is the case this binding exists for: a turn is in
        flight and Escape has nothing else to do.
        """
        if not self._busy or self._task is None or self._task.done():
            return False
        if self.app.screens.top.name in (PAGE_SCREEN, ASK_SCREEN):
            return False
        if self._menu_open() or self.view.selected_text() or self._follow_up_selecting:
            return False
        return not self._transcript_scrolled_up()

    def _interrupt_run(self, event: AnyEvent, host: Host) -> bool:
        """Stop the turn that is running, as Ctrl-C does and no more.

        Ctrl-C does more than this — it copies a selection, declines a question,
        closes a panel, and clears a draft — and this is only the part of it a
        reader reaches for while the shell is busy.
        """
        if not self._busy or self._task is None or self._task.done():
            return False
        self._task.cancel()
        host.invalidate()
        return True

    def _transcript_scrolled_up(self) -> bool:
        """Return whether Escape should jump the conversation back to its tail."""
        return self.app.screens.top.name != PAGE_SCREEN and self.view.scrolled_up

    def _scroll_end(self, event: AnyEvent, host: Host) -> bool:
        """Follow the newest line again, as the transcript's return badge does."""
        self.view.scroll_end()
        return True

    def _redraw(self, event: AnyEvent, host: Host) -> bool:
        """Repaint the frame, for a terminal that lost its contents."""
        host.refresh()
        return True

    def _scroll_up(self, event: AnyEvent, host: Host) -> bool:
        """Move the transcript one page toward older lines."""
        self.view.scroll_by(-3)
        return True

    def _scroll_down(self, event: AnyEvent, host: Host) -> bool:
        """Move the transcript one page toward newer lines."""
        self.view.scroll_by(3)
        return True

    def _quit(self, event: AnyEvent, host: Host) -> bool:
        """Leave the application."""
        host.exit()
        return True

    def _attach_image(self, event: AnyEvent, host: Host) -> bool:
        """Attach the clipboard's image to the draft, or say why there is none.

        Ctrl-V rather than the terminal's paste key: an image never reaches the
        program as input, so the shell has to go and look for it.

        Over ``ssh`` there is nothing to look at. The clipboard this process can read is the
        server's, an image the reader copied on their own machine never crosses the
        connection — a terminal carries text, not pictures — and a server rarely has a
        clipboard tool at all. So it does not look, and says so, instead of reporting "no
        image" and sending the reader to copy it again. ``ZETTCODE_CLIPBOARD=system`` is the
        reader saying the server's clipboard is the right one.
        """
        if copy_route() == "terminal":
            self.transcript.notice(
                "Ctrl-V cannot reach your clipboard over ssh — a terminal carries text, not pictures. "
                "Put the file on the server and refer to it by path, "
                "or set ZETTCODE_CLIPBOARD=system to read this machine's clipboard"
            )
            host.request_layout()
            return True
        try:
            image = read_image()
        except Exception as error:
            # Reading a clipboard is the shell reaching into the desktop, and a desktop can
            # fail in ways no tool list anticipates. The session is the reader's work: a
            # failed paste says what failed and leaves everything else as it was.
            self.transcript.error(f"could not read the clipboard: {describe_error(error)}")
            host.request_layout()
            return True
        if image is None:
            self.transcript.notice("no image on the clipboard")
        elif not self.agent.active_model.multimodal:
            self.transcript.error(f"{self.agent.active_model.shown_name} does not take images")
        else:
            label = self.composer.attach_image(*image)
            self._note = f"attached {label}"
        host.request_layout()
        return True

    def _accept_on_enter(self) -> bool:
        """Return whether Enter should complete the draft instead of running it.

        Completing is only useful while the highlighted command differs from
        what was typed; once the draft already spells it, Enter runs it instead
        of filling in the same text twice.
        """
        item = self.completions.current
        return item is not None and item.value != self.composer.text.strip()

    def _refresh_completions(self) -> None:
        """Mirror the composer's slash-command candidates into the menu."""
        # Nothing is offered over an entry the reader is only walking past: the menu would own
        # Up and Down from then on, and the walk through the history would stop at the first
        # command it met. Editing the entry (or typing from scratch) ends the walk and brings it back.
        candidates = () if self.composer.browsing_history else self.composer.completion_candidates()
        if candidates == self.completions.items:
            return
        self.completions.set_items(candidates, selected=0)
        self.app.request_layout()

    def _complete_next(self, event: AnyEvent, host: Host) -> bool:
        """Highlight the next command."""
        self.completions.move(1)
        host.invalidate()
        return True

    def _complete_previous(self, event: AnyEvent, host: Host) -> bool:
        """Highlight the previous command."""
        self.completions.move(-1)
        host.invalidate()
        return True

    def _complete_accept(self, event: AnyEvent, host: Host) -> bool:
        """Drop the highlighted command into the composer and close the menu."""
        item = self.completions.current
        if item is None:
            return False
        # The trailing space is what closes the menu: the draft is no longer a
        # bare command token, so the next Enter runs the command.
        self.composer.replace_token(item.value, suffix=" ")
        host.request_layout()
        return True

    def _complete_dismiss(self, event: AnyEvent, host: Host) -> bool:
        """Hide the menu until the draft changes again."""
        self.completions.set_items(())
        host.request_layout()
        return True

    def _interrupt(self, event: AnyEvent, host: Host) -> bool:
        """Copy a selection, otherwise stop the running turn or clear the draft."""
        selected = self.view.selected_text() or host.screen_selection_text()
        if selected:
            host.copy(selected)
            self.view.clear_selection()
            host.clear_screen_selection()
            host.invalidate()
            return True
        # A question the model is waiting on is answered or declined here: Ctrl-C
        # means the same thing Escape does on that panel, never a silent close
        # that would leave the tool call suspended.
        if self._asks:
            self._cancel_ask(self._asks[0])
            host.invalidate()
            return True
        if self.app.screens.top.name == PAGE_SCREEN:
            self.close_page()
            host.invalidate()
            return True
        if self._busy and self._task is not None and not self._task.done():
            self._task.cancel()
        elif self.composer.text:
            self.composer.clear()
        host.invalidate()
        return True

    def _toggle_thinking(self, event: AnyEvent, host: Host) -> bool:
        """Show or hide the newest reasoning block."""
        if self.transcript.toggle_latest_thinking():
            host.invalidate()
        return True
