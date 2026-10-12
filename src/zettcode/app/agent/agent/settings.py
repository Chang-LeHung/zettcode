"""What the reader can change about how the agent runs: model, reasoning effort, shell permission."""

from __future__ import annotations

from zett_agent.model import ReasoningEffort

from ....config import ModelConfig
from ..permission import PERMISSION_LEVELS, Permission
from .base import AgentBase


class SettingsMixin(AgentBase):
    """Read and change the model, the reasoning effort, and how much of the shell may run unasked."""

    @property
    def reduced_motion(self) -> bool:
        """Return whether decorative animation is disabled."""
        return self.runtime.config.reduced_motion

    @property
    def models(self) -> tuple[ModelConfig, ...]:
        """Return the models available for selection."""
        return self.runtime.config.models

    @property
    def active_model(self) -> ModelConfig:
        """Return the model selected for the next turn."""
        return self.runtime.active_model

    def use_model(self, name: str | ModelConfig) -> ModelConfig:
        """Select a configured model for subsequent turns."""
        return self.runtime.use_model(name)

    @property
    def effort(self) -> str:
        """Return the reasoning effort the next request will ask for."""
        return self.runtime.effort.value

    @property
    def efforts(self) -> tuple[str, ...]:
        """Return the reasoning levels the runtime accepts, cheapest first."""
        return tuple(level.value for level in ReasoningEffort)

    def use_effort(self, name: str) -> str:
        """Select a reasoning level for later requests and return its value."""
        return self.runtime.use_effort(name).value

    def approve_all_shell_commands(self) -> None:
        """Approve every shell command for the rest of this run, without asking."""
        self.runtime.approve_all_shell_commands()

    @property
    def permission(self) -> Permission:
        """Return how much of the shell may run without asking."""
        return self.runtime.permission

    @property
    def permissions(self) -> tuple[str, ...]:
        """Return the permission levels, strictest first."""
        return tuple(level.value for level in PERMISSION_LEVELS)

    def use_permission(self, name: str | Permission) -> Permission:
        """Set how much of the shell may run without asking, for the rest of this run."""
        return self.runtime.use_permission(name)
