"""Named commands and the contextual key bindings that trigger them."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeAlias

from .events import AnyEvent, KeyEvent, TextEvent
from .host import Host

CommandRun: TypeAlias = Callable[[AnyEvent, Host], bool]
BindingPriority: TypeAlias = str

_PRIORITIES = ("capture", "bubble")
_SEPARATORS = re.compile(r"[-+\s]+")


def normalize_key(value: str) -> str:
    """Fold every common spelling of a key into one canonical name."""
    return _SEPARATORS.sub("_", value.strip().lower())


def key_id(event: KeyEvent) -> str:
    """Return the binding name for a key event, including its modifiers.

    Args:
        event: Named key press; a modifier already folded into ``key`` is not
            repeated in the returned name.
    """
    name = normalize_key(event.key)
    prefixes = [
        modifier
        for modifier, active in (
            ("ctrl", event.control),
            ("alt", event.alt),
            ("shift", event.shift),
            ("meta", event.meta),
        )
        if active and not name.startswith(f"{modifier}_")
    ]
    return "_".join([*prefixes, name]) if prefixes else name


def event_key(event: AnyEvent) -> str | None:
    """Return the binding name an event resolves to, if it can be bound.

    Args:
        event: Any input event. A terminal delivers a printable character as
            text rather than as a named key, so a binding such as ``"q"`` has to
            be matched from that path as well; only single-character text
            qualifies, which keeps a paste from tripping a binding.
    """
    if isinstance(event, KeyEvent):
        return key_id(event)
    if isinstance(event, TextEvent) and len(event.text) == 1:
        return normalize_key(event.text)
    return None


@dataclass(frozen=True, slots=True)
class Command:
    """One named action a keymap or a command palette can invoke.

    Attributes:
        name: Unique lookup key, e.g. ``"interrupt"``.
        run: Receives the event and the host; returns whether it handled it.
        description: Human-readable text for a palette or a help screen.
    """

    name: str
    run: CommandRun
    description: str = ""


class CommandRegistry:
    """Look up commands by name and run them against the live host."""

    def __init__(self) -> None:
        """Start with no registered commands."""
        self._commands: dict[str, Command] = {}

    def register(self, command: Command) -> Command:
        """Add or replace a command and return it."""
        if not command.name:
            raise ValueError("Command name cannot be empty")
        self._commands[command.name] = command
        return command

    def add(self, name: str, run: CommandRun, *, description: str = "") -> Command:
        """Build a command from a name and a run function, then register it.

        Args:
            name: Lookup key; an existing command with the same name is replaced.
            run: Receives the event and the host, and reports whether it handled
                the event.
            description: Human-readable text for a palette or a help screen.
        """
        return self.register(Command(name, run, description))

    def get(self, name: str) -> Command | None:
        """Return a command by name, or None when it is not registered."""
        return self._commands.get(name)

    @property
    def names(self) -> tuple[str, ...]:
        """Return every registered command name, sorted."""
        return tuple(sorted(self._commands))

    def run(self, name: str, event: AnyEvent, host: Host) -> bool:
        """Run one command by name, reporting whether it handled the event."""
        command = self._commands.get(name)
        if command is None:
            return False
        return bool(command.run(event, host))


@dataclass(frozen=True, slots=True)
class Binding:
    """One key-to-command mapping, optionally limited to a live context.

    Attributes:
        command: Name resolved through the command registry.
        priority: ``"capture"`` runs before the widget tree sees the event,
            ``"bubble"`` only after the focused widget declines it.
        when: Predicate re-checked on every matching key; ``None`` always allows.
        description: Human-readable text for a palette or a help screen.
    """

    command: str
    priority: BindingPriority = "bubble"
    when: Callable[[], bool] | None = None
    description: str = ""

    def matches(self) -> bool:
        """Return whether the binding's predicate currently allows it."""
        return self.when is None or self.when()


class Keymap:
    """Contextual bindings split into capture and bubble priorities.

    Capture bindings run before the widget tree sees the event, so an
    application can reserve keys such as ``ctrl_c``. Bubble bindings run only
    after the focused widget declines the event, which lets a composer keep
    keys like ``tab`` for completion.
    """

    def __init__(self) -> None:
        """Start with no bindings."""
        self._bindings: dict[str, list[Binding]] = {}

    def bind(
        self,
        key: str,
        command: str,
        *,
        when: Callable[[], bool] | None = None,
        priority: BindingPriority = "bubble",
        description: str = "",
    ) -> Binding:
        """Bind a key spelling to a command at one priority.

        Args:
            key: Any spelling ``normalize_key`` folds, e.g. ``"Ctrl-C"``.
            command: Name looked up in the command registry when the key fires.
            when: Extra predicate sampled on every key press; the binding is
                skipped while it returns False.
            priority: ``"capture"`` or ``"bubble"``.
            description: Human-readable text for a palette or a help screen.

        Returns:
            The stored binding, so callers can keep it for a later unbind.
        """
        if priority not in _PRIORITIES:
            raise ValueError(f"Unknown binding priority: {priority!r}")
        if not command:
            raise ValueError("Binding command cannot be empty")
        binding = Binding(command, priority, when, description)
        self._bindings.setdefault(normalize_key(key), []).append(binding)
        return binding

    def unbind(self, key: str, command: str | None = None) -> int:
        """Remove bindings for one key and return how many were dropped.

        Args:
            key: Any spelling ``normalize_key`` folds.
            command: Only drop the binding that names this command; ``None``
                removes every binding registered for the key.
        """
        name = normalize_key(key)
        existing = self._bindings.get(name)
        if not existing:
            return 0
        if command is None:
            self._bindings.pop(name, None)
            return len(existing)
        kept = [binding for binding in existing if binding.command != command]
        if kept:
            self._bindings[name] = kept
        else:
            self._bindings.pop(name, None)
        return len(existing) - len(kept)

    def bindings_for(self, key: str) -> tuple[Binding, ...]:
        """Return the bindings registered for one key spelling, in order."""
        return tuple(self._bindings.get(normalize_key(key), ()))

    def resolve(self, event: AnyEvent, *, priority: BindingPriority = "bubble") -> str | None:
        """Return the first matching command name, if any binding applies."""
        name = event_key(event)
        if name is None:
            return None
        for binding in self._bindings.get(name, ()):
            if binding.priority == priority and binding.matches():
                return binding.command
        return None
