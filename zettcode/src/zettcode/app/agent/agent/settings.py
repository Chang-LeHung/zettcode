"""What the reader can change about how the agent runs: model, reasoning effort, shell permission."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

from zettcode.config import ModelConfig, _read_models
from zettcode.config_edit import (
    ConfigEditError,
    add_model,
    file_entries,
    remove_model,
    replace_model,
    set_pet,
    set_pet_position,
    set_self_compaction,
    set_statusline,
    set_theme,
    write_text_atomically,
)
from zettcode.paths import config_path
from zettcode.statusline import NAMES

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

    def change_compact_percent(self, percent: float) -> tuple[ModelConfig, str | None]:
        """Compact the model in use at ``percent`` of its window from the next request, and write it to the config file.

        The running session is changed whatever becomes of the file, since the reader asked for it now: a file
        that cannot be edited (no file, a layout the editor refuses) leaves the change for this run only, and the
        reason is returned beside the model so it can be said.

        Args:
            percent: Share of the window, more than 0 and at most 100.

        Returns:
            The model now in use, and why the file was not changed (``None`` when it was).

        Raises:
            ValueError: ``percent`` is not between 0 and 100.
        """
        if not 0 < percent <= 100:
            raise ValueError("The compression share must be more than 0 and at most 100.")
        active = self.active_model
        value = int(percent) if float(percent).is_integer() else percent
        try:
            for index, (model, entry) in enumerate(self.file_models()):
                if model == active:
                    return self.update_configured_model(index, {**entry, "compact_percent": value}), None
            reason = "the model in use is not in the config file"
        except ConfigEditError as error:
            reason = str(error)
        edited = replace(active, compact_percent=float(percent))
        models = tuple(edited if model is active else model for model in self.models)
        return self.runtime.replace_models(models), reason

    def remove_configured_model(self, index: int) -> ModelConfig:
        """Remove model number ``index`` (from zero) from the file and this session.

        Returns:
            The model in use afterwards: the one before unless it was the one removed.

        Raises:
            ConfigEditError: When it is the only model, or the file cannot be edited.
        """
        text = remove_model(self._read_config_file(), index, where=self.config_file)
        return self._commit_models(text)

    def remember_theme(self, name: str) -> Path:
        """Write ``[ui] theme = name`` into the config file, so the next start opens in that palette.

        Only that line changes. A config file that does not exist is not created for it: a file with nothing but
        ``[ui]`` in it would stand where a reader's environment-variable setup is, and say nothing about models.

        Returns:
            The file written.

        Raises:
            ConfigEditError: When there is no config file, it cannot be read or edited safely, or it cannot be
                written. Nothing is written then.
        """
        text = set_theme(self._read_config_file(), name, where=self.config_file)
        try:
            write_text_atomically(self.config_file, text)
        except OSError as error:
            raise ConfigEditError(f"{self.config_file} could not be written: {error}") from error
        return self.config_file

    def remember_pet(self, name: str) -> Path:
        """Write ``[ui] pet = name`` into the config file, so the next start opens with that pet.

        Only that line changes, and a config file that does not exist is not created for it. The pet in force
        for this run is the shell's to switch; what this keeps up to date is the setting the shell reads back.

        Returns:
            The file written.

        Raises:
            ConfigEditError: When there is no config file, it cannot be read or edited safely, or it cannot be
                written. Nothing is written then.
        """
        text = set_pet(self._read_config_file(), name, where=self.config_file)
        try:
            write_text_atomically(self.config_file, text)
        except OSError as error:
            raise ConfigEditError(f"{self.config_file} could not be written: {error}") from error
        self.runtime.config = replace(self.runtime.config, pet=name)
        return self.config_file

    def remember_pet_position(self, across: float, down: float) -> Path:
        """Write ``[ui] pet_position`` into the config file, so the next start puts the pet back where it was left.

        The file is global to the reader (``~/.zettcode/config.toml``), not to a project: a pet is the reader's
        companion, and it does not move house when they open another folder. Only that line changes, and a
        config file that does not exist is not created for it.

        Returns:
            The file written.

        Raises:
            ConfigEditError: When there is no config file, it cannot be read or edited safely, or it cannot be
                written. Nothing is written then.
        """
        text = set_pet_position(self._read_config_file(), across, down, where=self.config_file)
        try:
            write_text_atomically(self.config_file, text)
        except OSError as error:
            raise ConfigEditError(f"{self.config_file} could not be written: {error}") from error
        position = (round(min(1.0, max(0.0, across)), 3), round(min(1.0, max(0.0, down)), 3))
        self.runtime.config = replace(self.runtime.config, pet_position=position)
        return self.config_file

    @property
    def statusline_hidden(self) -> frozenset[str]:
        """Return the names of the header and status-line parts the reader switched off."""
        return frozenset(self.runtime.config.statusline_hidden)

    def remember_statusline(self, shown: Mapping[str, bool]) -> Path:
        """Write which parts of the header and status line are shown into ``[statusline]``.

        Only the parts that differ from what is in force are written. The file is written first and the
        running configuration changed second, so a write that fails leaves both as they were; the rows
        follow at the next paint. A config file that does not exist is not created for it, as for the theme.

        Args:
            shown: Part name to whether it is shown. A part left out keeps what it has.

        Returns:
            The file written.

        Raises:
            ConfigEditError: When there is no config file, it cannot be read or edited safely, or it cannot
                be written.
        """
        hidden = set(self.statusline_hidden)
        changes = {name: visible for name, visible in shown.items() if (name not in hidden) != visible}
        if not changes:
            return self.config_file
        text = set_statusline(self._read_config_file(), changes, where=self.config_file)
        try:
            write_text_atomically(self.config_file, text)
        except OSError as error:
            raise ConfigEditError(f"{self.config_file} could not be written: {error}") from error
        hidden = {name for name in hidden if name not in changes} | {name for name, v in changes.items() if not v}
        ordered = tuple(name for name in NAMES if name in hidden)
        self.runtime.config = replace(self.runtime.config, statusline_hidden=ordered)
        return self.config_file

    @property
    def self_compaction(self) -> bool:
        """Return whether the model may request compaction in this session right now."""
        return self.runtime.self_compacting(self.session_id)

    @property
    def self_compaction_choice(self) -> bool | None:
        """Return this session's own choice, or ``None`` when it follows the default."""
        return self.runtime.self_compaction_choice(self.session_id)

    @property
    def self_compaction_default(self) -> bool:
        """Return what a session that has made no choice does: ``[compaction] self`` in the config."""
        return self.runtime.config.self_compaction

    def use_self_compaction(self, choice: bool | None) -> None:
        """Set this session's own choice, or give it back with ``None`` so it follows the default.

        Raises:
            SessionLocked: Another process has the session open; the choice is part of the session.
            ConfigEditError: The choice could not be saved. Nothing is reported as saved then.
        """
        self.require_session()
        try:
            self.runtime.choose_self_compaction(self.session_id, choice)
        except OSError as error:
            raise ConfigEditError(f"Self-compaction setting was not saved: {error}") from error

    def remember_self_compaction(self, enabled: bool) -> Path:
        """Write ``[compaction] self = enabled`` into the config file: the default for every session.

        The file is written first and the running configuration changed second, so a write that fails
        leaves both as they were. A session with a choice of its own keeps it; one without follows this at
        once. A config file that does not exist is not created for it, as for the theme.

        Returns:
            The file written.

        Raises:
            ConfigEditError: When there is no config file, it cannot be read or edited safely, or it cannot
                be written.
        """
        text = set_self_compaction(self._read_config_file(), enabled, where=self.config_file)
        try:
            write_text_atomically(self.config_file, text)
        except OSError as error:
            raise ConfigEditError(f"{self.config_file} could not be written: {error}") from error
        self.runtime.config = replace(self.runtime.config, self_compaction=enabled)
        return self.config_file

    @property
    def effort(self) -> str:
        """Return the reasoning effort the next request will ask for."""
        return self.runtime.effort.value

    @property
    def efforts(self) -> tuple[str, ...]:
        """Return the reasoning levels the active model takes, cheapest first."""
        return tuple(level.value for level in self.runtime.active_model.efforts)

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
