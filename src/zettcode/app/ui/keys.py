"""The shell's keys: the keymap and every binding it registers.

The bindings are the shell's input vocabulary — scroll, redraw, attach, quit,
and the completion menu — and they live together so the keymap reads as one
table. :class:`ZettCodeApp` installs them once and never touches a key again.
"""

from __future__ import annotations

from ...tui import AnyEvent, Host
from .clipboard import read_image
from .shell import PAGE_SCREEN, ShellState


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
        self.app.commands.add("complete_accept", self._complete_accept)
        self.app.commands.add("complete_dismiss", self._complete_dismiss)
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

    def _menu_open(self) -> bool:
        """Return whether the slash-command menu is showing."""
        return self.app.screens.top.name != PAGE_SCREEN and self.completions.visible

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
        """Attach the clipboard's image to the draft, or say there is none.

        Ctrl-V rather than the terminal's paste key: an image never reaches the
        program as input, so the shell has to go and look for it.
        """
        image = read_image()
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
        candidates = self.composer.completion_candidates()
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
            self._note = f"copied {len(selected)} characters"
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
