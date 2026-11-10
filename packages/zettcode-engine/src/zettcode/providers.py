"""Providers: the hosts a plugin can offer models at, and the models it offers there.

A model entry needs an API (chat completions, the Responses API, or the Anthropic Messages API), an address, a
token and a model id. A plugin that knows a host can say so once and list the models it serves, so ``/model``
offers them without the reader typing an address or picking the wrong protocol; the token comes from the
environment variable the provider names, or from nothing at all for a local server.

This module knows nothing about the shell, the terminal or ``zett-agent`` — a plugin imports it to describe a host
of its own (``ctx.agent.register_provider(Provider(...))`` and ``ctx.agent.register_model(...)``) and the runtime
imports it to turn what a plugin offered into the same :class:`~zettcode.config.ModelConfig` a file entry becomes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from zettcode._compat import StrEnum

#: An environment variable name: what a provider names for the token its host wants.
ENVIRONMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")

#: What a provider is called when typed: lower case, so a name has one spelling.
NAME = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")


class Api(StrEnum):
    """The three request protocols one model entry can speak.

    The value is the name a reader types (``--api responses``), and a member compares equal to that string, so it
    can be used wherever the text was.

    Attributes:
        CHAT: An OpenAI-compatible chat-completions endpoint; the default.
        RESPONSES: The Responses API, on an OpenAI-compatible endpoint.
        ANTHROPIC: Anthropic's Messages API, which is not OpenAI-compatible.
    """

    CHAT = "chat"
    RESPONSES = "responses"
    ANTHROPIC = "anthropic"

    @property
    def label(self) -> str:
        """Return the API's own name, which is what a choice shows for it."""
        return _LABELS[self]

    @property
    def description(self) -> str:
        """Return what the protocol is, in words, for the line under that name."""
        return _DESCRIPTIONS[self]

    @property
    def keys(self) -> dict[str, object]:
        """Return the ``[[models]]`` keys that select this protocol: none for chat, one for the others.

        The three flags (``chat`` is the third) are alternatives, never layers, so a rewrite clears all of them before
        it sets one. Chat completions is what an entry that sets none already is, so it needs no key; a reader who
        picks it outright is given ``chat = true`` by the editor (see ``Draft.chat``), to say so in the file.
        """
        if self is Api.ANTHROPIC:
            return {"anthropic": True}
        if self is Api.RESPONSES:
            return {"responses_api": True}
        return {}

    @classmethod
    def parse(cls, text: str) -> Api:
        """Return the protocol a reader typed, in any case; raise ``ValueError`` listing the choices."""
        try:
            return cls(text.strip().lower())
        except ValueError:
            raise ValueError(f"the api must be one of {', '.join(cls)}, not {text!r}") from None


#: What each protocol is called beside its choice: the API a reader knows the endpoint by.
_LABELS = {
    Api.CHAT: "OpenAI Chat API",
    Api.RESPONSES: "OpenAI Responses API",
    Api.ANTHROPIC: "Anthropic Messages API",
}

#: How each protocol is described under its label. The wording rule for everything a list shows beside a name —
#: here, a protocol's description — is a lower-case phrase with no leading article and no full stop; a proper noun
#: (Responses API, Anthropic) keeps its capital.
_DESCRIPTIONS = {
    Api.CHAT: "chat completions",
    Api.RESPONSES: "OpenAI's Responses protocol, with hosted tools",
    Api.ANTHROPIC: "Anthropic's own protocol, not OpenAI-compatible",
}

#: The flags a ``[[models]]`` entry sets to choose a protocol; every one is cleared before one is set. ``chat`` is
#: among them because a file may spell the default out, and a rewrite to another protocol must not leave it behind.
API_FLAG_KEYS = ("chat", "anthropic", "responses_api")


@dataclass(frozen=True, slots=True)
class ProvidedModel:
    """One model a provider serves.

    Attributes:
        model: Model id sent to the endpoint; must not be blank.
        display_model: Name shown in ``/model``; ``None`` shows :attr:`model`.
        api: Which protocol this model speaks, when it differs from the provider's.
        base_url: The address for this model, when it differs from the provider's.
        multimodal: Whether it takes images, when it differs from the provider's default.
        context_window: Tokens it can carry, or ``None`` for the default the configuration uses.
        compact_percent: Share of the window at which a request is compacted first, in percent, or ``None``.
        reasoning_efforts: The levels it takes, cheapest first; empty means every level.
        temperature: Sampling temperature, or ``None`` for the endpoint's own.
        note: One line shown beside it in a list: a lower-case phrase with no leading article and no full stop.
    """

    model: str
    display_model: str | None = None
    api: Api | None = None
    base_url: str | None = None
    multimodal: bool | None = None
    context_window: int | None = None
    compact_percent: float | None = None
    reasoning_efforts: tuple[str, ...] = ()
    temperature: float | None = None
    note: str = ""

    def __post_init__(self) -> None:
        """Reject a model that could not become a configuration entry."""
        if not self.model.strip():
            raise ValueError("A provided model needs a model id")
        if self.display_model is not None:
            object.__setattr__(self, "display_model", self.display_model.strip() or None)
        if self.api is not None:
            object.__setattr__(self, "api", Api.parse(self.api))
        if self.base_url is not None:
            check_url(self.base_url, what=f"Provided model {self.model!r} base_url")
        if self.context_window is not None and self.context_window <= 0:
            raise ValueError(f"Provided model {self.model!r} needs a positive context window")
        if self.compact_percent is not None and not 0 < self.compact_percent <= 100:
            raise ValueError(f"Provided model {self.model!r} compacts between 1 and 100 percent of its window")
        for level in self.reasoning_efforts:
            if not isinstance(level, str) or not level.strip():
                raise ValueError(f"Provided model {self.model!r} names an empty reasoning level")

    @property
    def shown_name(self) -> str:
        """Return the name a list shows: the display name when it has one, else the model id."""
        return self.display_model or self.model


@dataclass(frozen=True, slots=True)
class Provider:
    """One host a plugin offers models at.

    Attributes:
        name: Identifier the host is registered under; lower case letters, digits, ``-`` and ``_``.
        label: What a list shows for the host.
        api: Which request protocol the host speaks, for models that do not name one: ``chat``, ``responses``
            or ``anthropic``.
        base_url: The address the client appends its route to, for models that do not name one. ``None`` leaves it to
            the SDK's own default, which is right for the vendor the SDK belongs to.
        token_env: The environment variable the token is read from when a model is used; ``None`` is a host that
            takes no key, as a local server does. It is read by the runtime, never written to the configuration.
        multimodal: Whether models at this host take images, as the default for one that does not say.
        models: The models the host serves, in the order a list should show them.
        note: One line of help shown beside the provider in a list.
    """

    name: str
    label: str
    api: Api = Api.CHAT
    base_url: str | None = None
    token_env: str | None = None
    multimodal: bool = False
    models: tuple[ProvidedModel, ...] = ()
    note: str = ""

    def __post_init__(self) -> None:
        """Reject a description that could not produce a working entry."""
        if not NAME.match(self.name):
            raise ValueError(
                f"Provider name {self.name!r} must be lower case letters, digits, '-' or '_', starting with a letter"
            )
        if not self.label.strip():
            raise ValueError(f"Provider {self.name!r} needs a label")
        try:
            object.__setattr__(self, "api", Api.parse(self.api))
        except ValueError as error:
            raise ValueError(f"Provider {self.name!r}: {error}") from None
        if self.base_url is not None:
            check_url(self.base_url, what=f"Provider {self.name!r} base_url")
        if self.token_env is not None and not ENVIRONMENT.match(self.token_env):
            raise ValueError(f"Provider {self.name!r} token_env must be an environment variable name")
        if any(not isinstance(model, ProvidedModel) for model in self.models):
            raise ValueError(f"Provider {self.name!r} lists something that is not a ProvidedModel")


def check_url(value: str, *, what: str = "url") -> str:
    """Return ``value`` trimmed if it is an http or https address, else raise ``ValueError``.

    Args:
        value: What the reader typed or a plugin declared.
        what: How to name it in the error.
    """
    cleaned = value.strip()
    parsed = urlparse(cleaned)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"{what} must be an http or https address such as https://api.example.com/v1")
    return cleaned
