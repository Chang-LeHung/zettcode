"""Providers: the hosts a model can be reached at, described once so ``/config`` can offer them.

A model entry needs an API (chat completions, Responses API, or Anthropic Messages API), an
address, a token and a model id. For a well-known host the first two are the same for everyone, so a
:class:`Provider` carries them and the reader only supplies the token and a model. A host nobody has
described is ``custom``: the reader gives the address too.

This module knows nothing about the shell, the terminal or ``zett-agent`` — a plugin imports it to
describe a host of its own (``container.register_provider(Provider(...))``) and the configuration
code imports it to turn a choice into a ``[[models]]`` entry.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urlparse

from ._compat import StrEnum


class Api(StrEnum):
    """The three request protocols one model entry can speak.

    The value is the name a reader types (``--api responses``) and the word the picker shows, and a
    member compares equal to that string, so it can be used wherever the text was.

    Attributes:
        CHAT: An OpenAI-compatible chat-completions endpoint; the default.
        RESPONSES: The Responses API, on an OpenAI-compatible endpoint.
        ANTHROPIC: Anthropic's Messages API, which is not OpenAI-compatible.
    """

    CHAT = "chat"
    RESPONSES = "responses"
    ANTHROPIC = "anthropic"

    @property
    def description(self) -> str:
        """Return what the protocol is, in words, for the question that asks for one."""
        return _DESCRIPTIONS[self]

    @property
    def keys(self) -> dict[str, object]:
        """Return the ``[[models]]`` keys that select this protocol: none for chat, one for the others.

        The two flags are alternatives, never layers, so a rewrite clears both before it sets one.
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


#: How each protocol is named beside a choice. The wording rule for everything a list shows next to a name — here,
#: a provider's :attr:`~Provider.note`, and the notes of the other pickers — is a lower-case phrase with no
#: leading article and no full stop; a proper noun (Responses API, Anthropic) keeps its capital.
_DESCRIPTIONS = {
    Api.CHAT: "chat completions",
    Api.RESPONSES: "Responses API",
    Api.ANTHROPIC: "Anthropic Messages API",
}

#: The flags a ``[[models]]`` entry sets to choose a protocol; every one is cleared before one is set.
API_FLAG_KEYS = ("anthropic", "responses_api")

#: What a provider is called when typed: lower case, so ``/config add deepseek`` has one spelling.
NAME = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")

#: The name that stands for "a host not described here"; it is not a provider, it is the absence of one.
CUSTOM = "custom"


@dataclass(frozen=True, slots=True)
class Provider:
    """One host a model can be reached at.

    Attributes:
        name: Identifier typed after ``/config add``; lower case letters, digits, ``-`` and ``_``.
        label: What the picker shows.
        api: Which request protocol the host speaks: ``chat``, ``responses`` or ``anthropic``.
        base_url: The address the client appends its route to. ``None`` leaves it to the SDK's own
            default, which is right for the vendor the SDK belongs to.
        token_env: The environment variable the vendor's own tools read the token from, named in
            the hint so a reader knows which key is wanted. It is never read from here.
        models: Model ids worth suggesting. Left empty by the built-ins: a list of model names goes
            stale faster than this program is released, so the reader types the one they mean.
        multimodal: Whether models at this host take images, as the default for a new entry.
        note: One line of help shown beside the provider in the picker: a lower-case phrase with no leading
            article and no full stop, as every note in a list is (``chat completions``, ``local models``).
            Left empty, the picker shows the protocol's own name.
    """

    name: str
    label: str
    api: Api = Api.CHAT
    base_url: str | None = None
    token_env: str | None = None
    models: tuple[str, ...] = ()
    multimodal: bool = False
    note: str = ""

    def __post_init__(self) -> None:
        """Reject a description that could not produce a working entry."""
        if not NAME.match(self.name):
            raise ValueError(
                f"Provider name {self.name!r} must be lower case letters, digits, '-' or '_', starting with a letter"
            )
        if self.name == CUSTOM:
            raise ValueError(f"{CUSTOM!r} is reserved: it stands for a host that is not described")
        if not self.label.strip():
            raise ValueError(f"Provider {self.name!r} needs a label")
        try:
            object.__setattr__(self, "api", Api.parse(self.api))
        except ValueError as error:
            raise ValueError(f"Provider {self.name!r}: {error}") from None
        if self.base_url is not None:
            check_url(self.base_url, what=f"Provider {self.name!r} base_url")


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


#: The hosts described out of the box. Each is an address and a protocol, nothing a reader could not
#: find on the vendor's own page; none of them lists models (see :attr:`Provider.models`).
BUILTIN_PROVIDERS: tuple[Provider, ...] = (
    Provider(
        "openai",
        "OpenAI",
        api=Api.CHAT,
        base_url="https://api.openai.com/v1",
        token_env="OPENAI_API_KEY",
        note="chat completions; change the api later for Responses API",
    ),
    Provider(
        "anthropic",
        "Anthropic",
        api=Api.ANTHROPIC,
        base_url="https://api.anthropic.com",
        token_env="ANTHROPIC_API_KEY",
        note="Anthropic Messages API",
    ),
    Provider(
        "deepseek",
        "DeepSeek",
        base_url="https://api.deepseek.com",
        token_env="DEEPSEEK_API_KEY",
        note="chat completions",
    ),
    Provider(
        "openrouter",
        "OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        token_env="OPENROUTER_API_KEY",
        note="chat completions; one key for many vendors, model ids look like vendor/name",
    ),
    Provider(
        "groq",
        "Groq",
        base_url="https://api.groq.com/openai/v1",
        token_env="GROQ_API_KEY",
        note="chat completions",
    ),
    Provider(
        "ollama",
        "Ollama (local)",
        base_url="http://localhost:11434/v1",
        note="chat completions on this machine; no key is checked, any text will do for the token",
    ),
)


def find_provider(name: str, providers: Iterable[Provider]) -> Provider | None:
    """Return the provider called ``name`` (case does not matter), or ``None``."""
    wanted = name.strip().lower()
    return next((provider for provider in providers if provider.name == wanted), None)


def merge_providers(*groups: Iterable[Provider]) -> tuple[Provider, ...]:
    """Join provider lists in order; the first to claim a name keeps it.

    A plugin that describes ``openai`` again does not replace the built-in: two hosts with one name
    would make ``/config add openai`` ambiguous, and the one that was there first is the one a
    reader has already seen.
    """
    merged: list[Provider] = []
    for group in groups:
        for provider in group:
            if all(existing.name != provider.name for existing in merged):
                merged.append(provider)
    return tuple(merged)
