"""What ``zettcode broker restart`` does about the background agents: stop them, and start them again afterwards.

A daemon is a session running headless on the broker. When the broker is replaced by one that speaks another protocol
it cannot reconnect and waits for ever, so a restart ends each daemon and, once the new broker is up, starts it again
on the same stored session, model, reasoning level, name and shell level. The conversation is not touched: a daemon is
only the process that runs it.
"""

from __future__ import annotations

from pathlib import Path

from ..broker.cli import Companions
from .process import Daemons, SpawnFailed
from .state import Registry, State


class DaemonCompanions(Companions):
    """The daemons on this machine, as the broker command sees them."""

    def __init__(self, registry: Registry | None = None) -> None:
        """Work on ``registry``, or on the machine's own."""
        self.daemons = Daemons(registry)
        self._stopped: list[State] = []

    def _alive(self) -> list[State]:
        return [r.state for r in self.daemons.registry.all() if r.state is not None and not r.dead]

    def listing(self) -> list[str]:
        """Return one line for each daemon whose process is running."""
        lines = []
        for state in self._alive():
            what = state.name or state.title or "-"
            lines.append(f"{state.session_id}  {what}  {state.workspace}")
        return lines

    def stop(self) -> list[str]:
        """Stop every running daemon, keeping what is needed to start it again."""
        records = [r for r in self.daemons.registry.all() if r.state is not None and not r.dead]
        # What is started again is exactly what was stopped here, not what a second look at the folder finds.
        self._stopped = [r.state for r in records if r.state is not None]
        return [f"{record.session_id}  {self.daemons.stop(record)}" for record in records]

    def start(self) -> list[tuple[bool, str]]:
        """Start each stopped daemon again on its own session."""
        results: list[tuple[bool, str]] = []
        for state in self._stopped:
            try:
                self.daemons.start(
                    Path(state.workspace),
                    model=state.model,
                    effort=state.effort,
                    resume=state.session_id,
                    name=state.name,
                    permission=state.permission or "safe",
                )
            except SpawnFailed as error:
                results.append((False, f"{state.session_id}  could not be started again: {error}"))
            else:
                results.append((True, f"{state.session_id}  started again"))
        self._stopped = []
        return results
