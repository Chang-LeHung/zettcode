"""What ``/config add`` means: turn a choice of provider and a few answers into one model entry.

The panel asks one question at a time and ``/config add`` takes everything on one line; both end up
here, so a model added either way is the same model. This module is plain data in and data out: it
knows nothing about widgets or the file, which is what makes the rules testable on their own.
"""

from __future__ import annotations

import shlex
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from ...providers import CUSTOM, Api, Provider, check_url, find_provider

USAGE = (
    "/config add <provider> [--model ID] [--token KEY] [--url URL] [--api chat|responses|anthropic] "
    "[--name SHOWN] [--multimodal]"
)

#: The flags ``/config add`` takes, and whether each one carries a value.
_FLAGS = {
    "--model": True,
    "--token": True,
    "--url": True,
    "--api": True,
    "--name": True,
    "--multimodal": False,
}


@dataclass(slots=True)
class Draft:
    """What is known about a model that is being added, filled in as it is learned.

    Attributes:
        provider: The described host the model is at, or ``None`` for a custom one.
        api: Which protocol it speaks. Starts as the provider's, and a reader may change it.
        url: The address; ``None`` is the SDK's own default.
        model: The model id sent to the endpoint.
        token: The credential.
        name: What the picker shows; empty means the model id.
        multimodal: Whether it takes images.
    """

    provider: Provider | None = None
    api: Api = Api.CHAT
    url: str | None = None
    model: str = ""
    token: str = ""
    name: str = ""
    multimodal: bool = False
    #: Which values the reader already gave on the command line, so the panel does not ask again.
    given: set[str] = field(default_factory=set)
    #: The questions answered in the panel, newest last, each with what was typed, so that
    #: Escape can take back the last one and show it again as it was answered.
    trail: list[tuple[str, str]] = field(default_factory=list)
    #: Whether the flow was entered from the panel's provider list, which is where Escape from
    #: the first question goes back to; from a typed line there is nothing behind it.
    from_panel: bool = False

    def undo(self) -> str | None:
        """Take back the last answer given in the panel; return what it was, or ``None`` if none was.

        The field goes back to being unanswered, so it is the next thing asked.
        """
        if not self.trail:
            return None
        name, previous = self.trail.pop()
        if name == "api":
            self.api = Api.CHAT
        elif name == "url":
            self.url = None
        elif name == "model":
            self.model = ""
        else:
            self.token = ""
        self.given.discard(name)
        return previous

    @classmethod
    def for_provider(cls, provider: Provider | None) -> Draft:
        """Start a draft with what the provider already says."""
        if provider is None:
            return cls()
        return cls(
            provider=provider,
            api=provider.api,
            url=provider.base_url,
            multimodal=provider.multimodal,
        )

    @property
    def custom(self) -> bool:
        """Return whether the host is one nobody described, so its address has to be asked."""
        return self.provider is None

    def missing(self) -> list[str]:
        """Return what still has to be asked, in the order to ask it."""
        wanted: list[str] = []
        if self.custom and "api" not in self.given:
            wanted.append("api")
        if (self.custom or self.url is None) and "url" not in self.given and self.api is not Api.ANTHROPIC:
            wanted.append("url")
        if not self.model:
            wanted.append("model")
        if not self.token:
            wanted.append("token")
        return wanted


def entry_for(draft: Draft) -> dict[str, object]:
    """Return the ``[[models]]`` keys a finished draft stands for.

    Raises:
        ValueError: When something required is missing or is not usable.
    """
    if not draft.model.strip():
        raise ValueError("A model id is required (--model)")
    if not draft.token.strip():
        raise ValueError("A token is required (--token)")
    entry: dict[str, object] = {"model": draft.model.strip(), "token": draft.token.strip()}
    if draft.name.strip():
        entry["display_model"] = draft.name.strip()
    if draft.url:
        entry["base_url"] = check_url(draft.url)
    elif draft.custom and draft.api is not Api.ANTHROPIC:
        raise ValueError("A custom provider needs an address (--url)")
    entry.update(draft.api.keys)
    if draft.multimodal:
        entry["multimodal"] = True
    return entry


def parse_add(argument: str, providers: Sequence[Provider]) -> Draft:
    """Read what follows ``/config add`` into a draft, which may still be missing answers.

    Args:
        argument: The text after ``add``: a provider name (or ``custom``) and optional flags.
        providers: The hosts that can be named.

    Raises:
        ValueError: With a sentence saying what is wrong and how to write it.
    """
    try:
        words = shlex.split(argument)
    except ValueError as error:
        raise ValueError(f"cannot read that: {error}") from error
    if not words or words[0].startswith("--"):
        names = ", ".join([*(provider.name for provider in providers), CUSTOM])
        raise ValueError(f"Name the provider: one of {names}\nUsage: {USAGE}")
    name, flags = words[0].lower(), _flags(words[1:])
    provider = None if name == CUSTOM else find_provider(name, providers)
    if provider is None and name != CUSTOM:
        known = ", ".join([*(item.name for item in providers), CUSTOM])
        raise ValueError(f"Unknown provider {words[0]!r}; use one of {known}")
    draft = Draft.for_provider(provider)
    if "--api" in flags:
        try:
            draft.api = Api.parse(flags["--api"])
        except ValueError as error:
            raise ValueError(f"--api: {error}") from None
        draft.given.add("api")
    if "--url" in flags:
        draft.url = check_url(flags["--url"], what="--url")
        draft.given.add("url")
    if "--model" in flags:
        draft.model = flags["--model"].strip()
    if "--token" in flags:
        draft.token = flags["--token"].strip()
    if "--name" in flags:
        draft.name = flags["--name"].strip()
    if "--multimodal" in flags:
        draft.multimodal = True
    return draft


def _flags(words: Sequence[str]) -> Mapping[str, str]:
    """Read ``--flag value`` pairs; a flag that takes no value maps to the empty string."""
    found: dict[str, str] = {}
    index = 0
    while index < len(words):
        word = words[index]
        if word not in _FLAGS:
            raise ValueError(f"Unknown option {word!r}\nUsage: {USAGE}")
        if word in found:
            raise ValueError(f"{word} was given twice")
        if _FLAGS[word]:
            if index + 1 >= len(words) or words[index + 1].startswith("--"):
                raise ValueError(f"{word} needs a value\nUsage: {USAGE}")
            found[word] = words[index + 1]
            index += 2
        else:
            found[word] = ""
            index += 1
    return found


def describe(entry: Mapping[str, object]) -> str:
    """Return one line saying what an entry is, with the token never shown."""
    api = Api.ANTHROPIC if entry.get("anthropic") else Api.RESPONSES if entry.get("responses_api") else Api.CHAT
    url = entry.get("base_url") or "default address"
    return f"{entry.get('display_model') or entry['model']} \u00b7 {entry['model']} \u00b7 {api} \u00b7 {url}"
