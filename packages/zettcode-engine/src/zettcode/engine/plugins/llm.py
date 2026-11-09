"""The model service a plugin reaches without going through a command or the shell."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

from zettcode.config import ModelConfig


class ModelAccess:
    """The configured models, and the side question a plugin may ask of the active one.

    The service is built with the runtime's configuration, so every model the reader configured is available from
    the moment a plugin activates. The question side is bound later by the front end that owns the conversation;
    until then :meth:`ask` says the conversation is not ready instead of reaching for a client it does not have.

    Ask a question with the plugin's name as ``origin``. The exchange is kept out of the conversation and a plugin's
    question is not restored into a resumed transcript, which is what lets a recap or an audit ask for itself.
    """

    def __init__(self, models: Sequence[ModelConfig]) -> None:
        """Keep every configured model and no ask yet."""
        self._models = tuple(models)
        self._ask: Callable[..., Awaitable[str]] | None = None

    @property
    def models(self) -> tuple[ModelConfig, ...]:
        """Return every model the reader configured, in the order the configuration lists them."""
        return self._models

    def bind(self, ask: Callable[..., Awaitable[str]]) -> None:
        """Give the service the conversation's side-question entry point; the front end is the caller."""
        self._ask = ask

    async def ask(
        self,
        question: str,
        *,
        origin: str = "plugin",
        cache: str = "read",
        timeout: float | None = None,
    ) -> str:
        """Ask a side question about this conversation and return the answer.

        Args:
            question: What to ask; blank is refused by the conversation.
            origin: Who asks; a plugin uses its own name so a resumed transcript leaves the exchange out.
            cache: How the provider's prompt cache may be used; a side question defaults to ``"read"``.
            timeout: How long to wait, or ``None`` for the conversation's default.

        Raises:
            RuntimeError: The front end has not bound the conversation yet.
        """
        if self._ask is None:
            raise RuntimeError("The conversation is not ready to answer side questions yet")
        return await self._ask(question, origin=origin, cache=cache, timeout=timeout)
