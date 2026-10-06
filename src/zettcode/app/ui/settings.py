"""The shell's pickers: model, palette, and reasoning effort.

A picker page hands its choice back through one of these methods, which applies
it through the agent and closes the page. Keeping them here leaves the shell
class the wiring and the turn loop rather than one method per setting.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...tui import Theme, theme_named
from .shell import ShellState

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from ...config import ModelConfig


class SettingsMixin(ShellState):
    """Apply the setting a picker returned and return to the composer."""

    def close_page(self) -> None:
        """Return to the composer, restoring its focus and layout."""
        self.app.pop_screen()
        self.app.request_layout()

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
        """Switch the palette and repaint.

        Widgets read ``theme`` while painting, so nothing has to be rebuilt;
        the invalidate is what makes the new colours land, and the re-layout
        covers the caches a size-only change would have missed.
        """
        theme = theme_named(name)
        self.app.theme = theme
        self.app.request_layout()
        return theme

    def select_theme(self, name: str) -> None:
        """Apply the palette picked in the panel and return to the composer."""
        try:
            self.apply_theme(name)
        except ValueError as error:
            self.transcript.error(str(error))
        self.close_page()

    def change_effort(self, name: str) -> str:
        """Switch reasoning effort and announce the change in the transcript."""
        previous = self.agent.effort
        selected = self.agent.use_effort(name)
        if selected != previous:
            self.transcript.effort_changed(previous, selected)
        return selected

    def select_effort(self, name: str) -> None:
        """Apply the reasoning level picked in the panel and return to the composer."""
        try:
            self.change_effort(name)
        except ValueError as error:
            self.transcript.error(str(error))
        self.close_page()
        self.app.request_layout()
