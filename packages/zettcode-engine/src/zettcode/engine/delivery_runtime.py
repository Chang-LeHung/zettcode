"""The runtime's own :class:`~zettcode.engine.delivery.Delivery`: steer the turn in flight, hear when it ends.

The engine cannot build this before the runtime exists — a plugin activates while the runtime is being constructed — so
:meth:`ZettCodeEngine.preview` makes an empty one, hands it to the plugins by name, and binds it once the runtime is
there. Nothing calls it before that: a plugin only keeps it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from .delivery import Delivery

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zett_agent.messages import UserMessage

    from .core import ZettCodeEngine

__all__ = ["RuntimeDelivery"]


class RuntimeDelivery(Delivery):
    """The runtime's delivery: nothing until it is bound to a runtime, and everything the runtime can do after."""

    def __init__(self) -> None:
        self._runtime: ZettCodeEngine | None = None

    def bind(self, runtime: ZettCodeEngine) -> None:
        """Point the delivery at the runtime it delivers to; ``preview`` calls it once the runtime is built."""
        self._runtime = runtime

    @property
    def busy(self) -> bool:
        """Return whether a request is running."""
        return self._runtime is not None and self._runtime.running

    def steer(self, message: str | UserMessage) -> str | None:
        """Hand a message to the request in flight, and say what it will be reported by."""
        runtime = self._runtime
        if runtime is None:
            return None
        from .agent.turns import steer_in_flight

        payload: dict[str, object] = {"content": message} if isinstance(message, str) else {"message": message}
        if not steer_in_flight(runtime, runtime.session_id, payload):
            return None
        return message if isinstance(message, str) else message.text

    def when_idle(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Call ``callback`` when the last request ends; at once when nothing runs."""
        runtime = self._runtime
        if runtime is None or not runtime.running:
            callback()
            return lambda: None
        return runtime.on_idle(callback)
