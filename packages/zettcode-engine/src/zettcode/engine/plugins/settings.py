"""The keys one plugin reads from the configuration, and the defaults it supplies for them.

The configuration file cannot know which plugins are installed or what their keys mean, so it keeps each plugin's
table as it was written (``[plugins.recap] after_seconds = 180``). A plugin says what it reads and what the value is
when the reader has not written one; from then on the reader's value wins, checked against the default's type, and a
key the plugin never declared is an error rather than a silent default.

::

    given = ctx.settings.declare(after_seconds=180, cache_ttl_seconds=300)
    after = given["after_seconds"]      # 180, or what [plugins.recap] says

A type is the default's: a whole number for an ``int``, true or false for a ``bool``, text for a ``str``, and a number
for a ``float`` (a whole one is accepted and comes back as a float). Anything else — a list, a table, a string where a
number was declared — is refused when the plugin activates, naming the plugin, the key and the file it came from.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeAlias

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from collections.abc import Mapping

#: What a plugin's settings may hold: what TOML calls a scalar.
Value: TypeAlias = bool | int | float | str

__all__ = ["PluginSettings", "Value"]


def _matches(value: object, default: Value) -> bool:
    """Return whether a value from the file has the type its declared default has."""
    if isinstance(default, bool):
        return isinstance(value, bool)
    if isinstance(default, int):
        return isinstance(value, int) and not isinstance(value, bool)
    if isinstance(default, float):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, str)


#: How each type is described in a refusal, in the words a reader of the file would use.
_WORDS = {bool: "true or false", int: "a whole number", float: "a number", str: "text"}


def _as_written(value: object, default: Value) -> Value:
    """Return the reader's value as the default's type, or raise naming what was expected."""
    if not _matches(value, default):
        expected = _WORDS[type(default)]
        raise ValueError(f"must be {expected}, not {type(value).__name__}")
    if isinstance(default, float) and isinstance(value, int):
        return float(value)
    return value  # type: ignore[return-value]  # narrowed by `_matches`


class PluginSettings:
    """The keys one plugin declares, with the reader's values in front of its defaults.

    Args:
        plugin: The plugin's name, which is the entry-point name a ``[plugins.<name>]`` table is written under.
        given: What the reader wrote in that table, checked as each key is declared.
    """

    def __init__(self, plugin: str = "", given: Mapping[str, object] | None = None) -> None:
        """Keep the plugin's name and the values the reader wrote, if any."""
        self.plugin = plugin
        self._given: dict[str, object] = dict(given or {})
        self._defaults: dict[str, Value] = {}

    def declare(self, **defaults: object) -> dict[str, object]:
        """Declare the keys the plugin reads and return the values in effect.

        Declaring the same key twice keeps the first default, so two call sites cannot disagree about what the
        value means; the reader's value is applied to whichever default was declared first.

        Args:
            **defaults: One default per key, whose type is the type the reader's value must have.

        Returns:
            Each declared key with the reader's value when there is one, else the default.

        Raises:
            ValueError: A default is not a scalar, or the reader's value for a key is not the declared type.
        """
        for key, default in defaults.items():
            if not isinstance(default, (bool, int, float, str)):
                raise ValueError(f"{self._where(key)} declares a default that is not a string, a number or a boolean")
            self._defaults.setdefault(key, default)
        return {key: self.get(key) for key in defaults}

    def get(self, key: str) -> Value:
        """Return the value in effect for one declared key.

        Raises:
            ValueError: The plugin never declared that key (reading it would always be a default it never chose),
                or the reader's value is not the type the default declares.
        """
        if key not in self._defaults:
            raise ValueError(f"{self._where(key)} is not a setting this plugin declared")
        default = self._defaults[key]
        if key not in self._given:
            return default
        value = self._given[key]
        try:
            return _as_written(value, default)
        except ValueError as error:
            hint = f" (declared as {type(default).__name__})" if isinstance(default, float) else ""
            raise ValueError(f"{self._where(key)} {error}{hint}") from None

    def values(self) -> dict[str, object]:
        """Return every declared key with the value in effect, for a plugin that wants them all at once."""
        return {key: self.get(key) for key in self._defaults}

    def _where(self, key: str) -> str:
        """Return the place a problem is reported against: the plugin's table when it has a name."""
        table = f"[plugins.{self.plugin}]" if self.plugin else "the plugin settings"
        return f"Config key {key!r} in {table}"
