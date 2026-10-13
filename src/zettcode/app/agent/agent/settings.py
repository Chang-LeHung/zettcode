"""What the reader can change about how the agent runs: model, reasoning effort, shell permission."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from zett_agent.model import ReasoningEffort

from ....config import ModelConfig, _read_models
from ....config_edit import (
    ConfigEditError,
    add_model,
    file_entries,
    remove_model,
    replace_model,
    write_text_atomically,
)
from ....paths import config_path
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

    def find_model(self, name: str) -> ModelConfig | None:
        """Return the configured model a recorded name stands for, if exactly one does."""
        return self.runtime.find_model(name)

    def use_model(self, name: str | ModelConfig) -> ModelConfig:
        """Select a configured model for subsequent turns."""
        return self.runtime.use_model(name)

    # -- the models in the config file --------------------------------------------------
    @property
    def config_file(self) -> Path:
        """Return the file the models are read from and written to."""
        return config_path()

    def _read_config_file(self) -> str:
        """Return the config file's text, or raise :class:`ConfigEditError` saying why not."""
        path = self.config_file
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise ConfigEditError(f"{path} does not exist") from error
        except (OSError, UnicodeDecodeError) as error:
            raise ConfigEditError(f"{path} cannot be read: {error}") from error

    def file_models(self) -> tuple[tuple[ModelConfig, Mapping[str, object]], ...]:
        """Return each model in the file with the keys the file writes for it.

        The file is the source of truth for editing, not the models the session started with: a
        reader may have changed it by hand since. The keys are what is *written* — a token left to
        an environment variable is absent — which is what a rewrite has to start from.

        Raises:
            ConfigEditError: When the file cannot be read, is not valid, or lays its models out in
                a way the editor cannot safely change.
        """
        text = self._read_config_file()
        path = self.config_file
        entries = file_entries(text, where=path)
        try:
            models = _read_models(entries, path)
        except ValueError as error:
            raise ConfigEditError(str(error)) from error
        return tuple(zip(models, entries, strict=True))

    def _commit_models(self, text: str) -> ModelConfig:
        """Write the edited text, then make the running session use what it now says.

        The file is written first and the session is changed second, so a write that fails leaves
        the session as it was, and what the session holds is always something the file holds too.
        """
        path = self.config_file
        try:
            write_text_atomically(path, text)
        except OSError as error:
            raise ConfigEditError(f"{path} could not be written: {error}") from error
        models = _read_models(file_entries(text, where=path), path)
        return self.runtime.replace_models(models)

    def add_configured_model(self, entry: Mapping[str, object]) -> ModelConfig:
        """Add one ``[[models]]`` entry to the file and to this session; return the new model.

        The model in use does not change: adding is not choosing. The new one appears in ``/model``.

        Args:
            entry: The keys of the new model as the file writes them.

        Raises:
            ConfigEditError: When the entry is not a model that can be called, or the file cannot
                be edited. Nothing is written then.
        """
        text = add_model(self._read_config_file(), entry, where=self.config_file)
        self._commit_models(text)
        return self.runtime.config.models[-1]

    def update_configured_model(self, index: int, entry: Mapping[str, object]) -> ModelConfig:
        """Rewrite model number ``index`` (from zero) of the file as ``entry``; return the result."""
        text = replace_model(self._read_config_file(), index, entry, where=self.config_file)
        self._commit_models(text)
        return self.runtime.config.models[index]

    def remove_configured_model(self, index: int) -> ModelConfig:
        """Remove model number ``index`` (from zero) from the file and this session.

        Returns:
            The model in use afterwards: the one before unless it was the one removed.

        Raises:
            ConfigEditError: When it is the only model, or the file cannot be edited.
        """
        text = remove_model(self._read_config_file(), index, where=self.config_file)
        return self._commit_models(text)

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
