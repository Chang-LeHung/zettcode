"""What the reader can change about how the agent runs: model, reasoning effort, shell permission."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

from zettcode.config import NO_MODEL_REFUSAL, ModelConfig, _read_models
from zettcode.config_edit import (
    ConfigEditError,
    add_model,
    file_entries,
    remove_model,
    replace_model,
    set_self_compaction,
    write_text_atomically,
)
from zettcode.engine.permission import PERMISSION_LEVELS, Permission
from zettcode.paths import config_path

from .base import AgentBase


class SettingsMixin(AgentBase):
    """Read and change the model, the reasoning effort, and how much of the shell may run unasked."""

    @property
    def models(self) -> tuple[ModelConfig, ...]:
        """Return the models available for selection."""
        return self.runtime.config.models

    @property
    def active_model(self) -> ModelConfig | None:
        """Return the model selected for the next turn, or ``None`` when this machine has none configured."""
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

    def _read_config_file(self, *, allow_missing: bool = False) -> str:
        """Return the config file's text, or raise :class:`ConfigEditError` saying why not.

        Args:
            allow_missing: Answer an empty file when there is none. Only what sets a machine up asks for that —
                the first model, and the list that shows there is nothing to list — because a fresh machine has
                no config file at all. Every other edit treats a missing file as the reader's file that vanished
                and says so, rather than writing a new one that would hold none of what theirs did.
        """
        path = self.config_file
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError as error:
            if allow_missing:
                return ""
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
        text = self._read_config_file(allow_missing=not self.models)
        path = self.config_file
        entries = file_entries(text, where=path)
        try:
            # A file that lists none is a list with nothing in it, not a refusal: `/config` is how the first
            # one is written, so the panel it opens must be able to show an empty file.
            models = _read_models(entries, path, required=False)
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

        The model in use does not change: adding is not choosing. The new one appears in ``/model``. The exception
        is the first model a machine has — there is nothing to add it beside — so that one becomes the model in
        use, and it is chosen here rather than by the file's order: another process may have written an entry
        since this session started, and ``/config`` announces the entry it just wrote, not that one.

        Args:
            entry: The keys of the new model as the file writes them.

        Raises:
            ConfigEditError: When the entry is not a model that can be called, or the file cannot
                be edited. Nothing is written then.
        """
        text = add_model(self._read_config_file(allow_missing=not self.models), entry, where=self.config_file)
        first = self.runtime.active_model is None
        self._commit_models(text)
        model = self.runtime.config.models[-1]
        return self.runtime.use_model(model) if first else model

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
            ValueError: ``percent`` is not between 0 and 100, or no model is configured to compact.
        """
        if not 0 < percent <= 100:
            raise ValueError("The compression share must be more than 0 and at most 100.")
        if self.runtime.active_model is None:
            raise ValueError(NO_MODEL_REFUSAL)
        active = self.runtime.required_model
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
        """Return the reasoning levels the active model takes, cheapest first; none when no model is configured."""
        model = self.runtime.active_model
        return () if model is None else tuple(level.value for level in model.efforts)

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

    def use_permission(self, name: str | Permission, *, remember: bool = True) -> Permission:
        """Set how much of the shell may run without asking, and by default remember it for this session."""
        return self.runtime.use_permission(name, remember=remember)

    @property
    def harness(self) -> bool:
        """Return whether the just-in-time harness is on for the next request."""
        return self.runtime.harness.on

    def use_harness(self, on: bool) -> bool:
        """Turn the just-in-time harness on or off for later requests, for the rest of this run."""
        return self.runtime.use_harness(on)
