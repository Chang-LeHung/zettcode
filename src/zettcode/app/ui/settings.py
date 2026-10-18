"""The shell's pickers: model, palette, pet, and reasoning effort.

A picker page hands its choice back through one of these methods, which applies
it through the agent and closes the page. Keeping them here leaves the shell
class the wiring and the turn loop rather than one method per setting.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from zettcode.tui import Theme

from .shell import ShellState

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zettcode.config import ModelConfig

    from ..pets import Pet


class SettingsMixin(ShellState):
    """Apply the setting a picker returned and return to the composer."""

    def close_page(self) -> None:
        """Return to the composer, restoring its focus and layout."""
        self.app.pop_screen()
        self.app.request_layout()

    def request_layout(self) -> None:
        """Lay the screen out again; the one call a command makes when what it changed alters the rows."""
        self.app.request_layout()

    def offer(self, command: str) -> None:
        """Put the command and a space in the draft, which opens the menu of the words it takes."""
        self.composer.set_text(f"{command} ")

    def quit(self) -> None:
        """Leave the application."""
        self.app.exit()

    def change_model(self, name: ModelConfig | str) -> ModelConfig:
        """Switch models and announce the change in the transcript."""
        previous = self.agent.active_model
        selected = self.agent.use_model(name)
        if selected is not previous:
            self.transcript.model_changed(previous.shown_name, selected.shown_name)
        self.app.request_layout()
        return selected

    def select_model(self, name: ModelConfig) -> None:
        """Apply the highlighted model and return to the composer."""
        try:
            self.change_model(name)
        except ValueError as error:
            self.transcript.error(str(error))
        self.close_page()

    def apply_theme(self, name: str) -> Theme:
        """Switch the palette to the one called ``name`` and repaint.

        The name is a built-in palette or a file of the reader's (``~/.zettcode/themes/<name>.toml``).
        Widgets read ``theme`` while painting, so nothing has to be rebuilt;
        the invalidate is what makes the new colours land, and the re-layout
        covers the caches a size-only change would have missed.

        Raises:
            ValueError: There is no such palette, or its file cannot be read; the message lists the ones there are.
        """
        theme = self.agent.themes.load(name)
        self._theme_before = None  # what is applied is not a preview to be put back
        self.app.theme = theme
        self.app.request_layout()
        return theme

    def preview_theme(self, name: str | None) -> None:
        """Show a palette without choosing it, or put back the one that was in force.

        Called as the highlight moves through the ``/theme`` menu: the whole interface is repainted in the
        highlighted palette so it can be judged on the conversation in front of the reader, and the palette that
        was in force is kept to be restored when the menu goes away without a choice. A palette that cannot be
        loaded is simply not shown; the error belongs to the reader who picks it.

        Args:
            name: The palette to show, or ``None`` to end the preview and restore.
        """
        if name is None:
            if self._theme_before is not None:
                self.app.theme, self._theme_before = self._theme_before, None
                self.app.request_layout()
            return
        try:
            theme = self.agent.themes.load(name)
        except ValueError:
            return
        if self._theme_before is None:
            self._theme_before = self.app.theme
        if theme != self.app.theme:
            self.app.theme = theme
            self.app.request_layout()

    def apply_pet(self, name: str) -> Pet:
        """Put the pet called ``name`` over the conversation, where the last one stood.

        Raises:
            ValueError: There is no such pet, or it cannot be built; the message lists the ones there are.
        """
        pet = self.agent.pets.load(name)
        self._pet_before = None  # what is applied is not a preview to be put back
        self.pet.set_pet(pet)
        self.app.invalidate()
        return pet

    def preview_pet(self, name: str | None) -> None:
        """Show a pet without choosing it, or put back the one that was there.

        Called as the highlight moves through the ``/pet`` menu, so each pet can be judged where it will stand.
        The pet that was there is kept to be restored when the menu goes away without a choice. A pet that cannot
        be built is simply not shown; the error belongs to the reader who picks it.

        Args:
            name: The pet to show, or ``None`` to end the preview and restore.
        """
        if name is None:
            if self._pet_before is not None:
                self.pet.set_pet(self._pet_before)
                self._pet_before = None
                self.app.invalidate()
            return
        try:
            pet = self.agent.pets.load(name)
        except ValueError:
            return
        if self._pet_before is None:
            self._pet_before = self.pet.pet
        self.pet.set_pet(pet)
        self.app.invalidate()

    def change_effort(self, name: str) -> str:
        """Switch reasoning effort, run the header's gauge, and announce the change in the transcript."""
        previous = self.agent.effort
        selected = self.agent.use_effort(name)
        if selected != previous:
            self.transcript.effort_changed(previous, selected)
            self.start_effort_animation(previous, selected)
        return selected

    def change_permission(self, name: str) -> str:
        """Set how much of the shell may run unasked and announce the change.

        Takes effect on the next command, including one in the request that is
        running now, because the policy is read at each shell call rather than
        when the request starts.
        """
        previous = self.agent.permission
        selected = self.agent.use_permission(name)
        if selected != previous:
            self.transcript.permission_changed(previous.value, selected.value)
        self.app.invalidate()
        return selected.value
