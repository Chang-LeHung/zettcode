"""What the reader can change about how the terminal looks: theme, pet, which parts of the status line are shown.

These are the terminal's own preferences. They are kept in the same config file as the engine's settings, and are
written the same way, which is why this reads the file through the engine's helpers.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

from zettcode.config_edit import (
    ConfigEditError,
    set_pet,
    set_pet_position,
    set_statusline,
    set_theme,
    write_text_atomically,
)
from zettcode.engine.agent.settings import SettingsMixin
from zettcode.statusline import NAMES


class AppearanceMixin(SettingsMixin):
    """Read and remember the terminal's theme, pet and status line."""

    @property
    def reduced_motion(self) -> bool:
        """Return whether decorative animation is disabled."""
        return self.runtime.config.reduced_motion

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
        # The program's parts in their order, then the ones a plugin added (their names are not in NAMES).
        ordered = (*(name for name in NAMES if name in hidden), *sorted(hidden - set(NAMES)))
        self.runtime.config = replace(self.runtime.config, statusline_hidden=ordered)
        return self.config_file
