"""What ``/config add`` means: turn a choice of provider and a few answers into one model entry.

The panel asks one question at a time and ``/config add`` takes everything on one line; both end up
here, so a model added either way is the same model. This module is plain data in and data out: it
knows nothing about widgets or the file, which is what makes the rules testable on their own.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, TypeVar

from zettcode.providers import CUSTOM, Api, Provider, check_url, find_provider

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zettcode.sdk.types import ModelInfo

T = TypeVar("T")

USAGE = (
    "/config add <provider> [--model ID] [--token KEY] [--url URL] [--api chat|responses|anthropic] "
    "[--name SHOWN] [--multimodal] [--context TOKENS] [--compact PERCENT] [--temperature T] "
    "[--web-search] [--search-tool TYPE]"
)

#: The smallest context window the panel accepts. A window is counted in tokens, so a small number is nearly always a
#: window written in thousands (``200``); the file itself would take it, and the model would be compacted at once.
MIN_CONTEXT_WINDOW = 1_000

#: The flags ``/config add`` takes, and whether each one carries a value.
_FLAGS = {
    "--model": True,
    "--token": True,
    "--url": True,
    "--api": True,
    "--name": True,
    "--multimodal": False,
    "--context": True,
    "--compact": True,
    "--temperature": True,
    "--web-search": False,
    "--search-tool": True,
}


@dataclass(slots=True)
class Draft:
    """What is known about a model that is being added, filled in as it is learned.

    Attributes:
        provider: The described host the model is at, or ``None`` for a custom one.
        api: Which protocol it speaks. Starts as the provider's, and a reader may change it.
        url: The address; ``None`` is the SDK's own default.
        model: The model id sent to the endpoint.
        token: The credential. May stay empty: a local server wants none, and the environment can supply one.
        name: What the picker shows; empty means the model id.
        multimodal: Whether it takes images.
        context_window: Tokens it can carry; ``None`` leaves the default.
        compact_percent: The share of the window at which a request is summarized first; ``None`` leaves the default.
        temperature: The sampling temperature; ``None`` sends none.
        web_search: Whether the provider searches the web for the model.
        search_tool: The tool type that search is sent as; empty takes the default for the API.
    """

    provider: Provider | None = None
    api: Api = Api.CHAT
    url: str | None = None
    model: str = ""
    token: str = ""
    name: str = ""
    multimodal: bool = False
    context_window: int | None = None
    compact_percent: float | None = None
    temperature: float | None = None
    web_search: bool = False
    search_tool: str = ""
    #: Whether the reader picked chat completions outright (from the list, or ``--api chat``), which is written as
    #: ``chat = true``; a provider whose protocol is chat by default does not ask, and writes nothing.
    chat: bool = False
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
            self.chat = False
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
        """Return what still has to be asked, in the order to ask it.

        The token is asked about, not required: a draft that was not told one (``--token``) is shown to the reader
        with the line empty, and an empty line is a valid answer.
        """
        wanted: list[str] = []
        if self.custom and "api" not in self.given:
            wanted.append("api")
        if (self.custom or self.url is None) and "url" not in self.given and self.api is not Api.ANTHROPIC:
            wanted.append("url")
        if not self.model:
            wanted.append("model")
        if "token" not in self.given:
            wanted.append("token")
        return wanted


def entry_for(draft: Draft) -> dict[str, object]:
    """Return the ``[[models]]`` keys a finished draft stands for.

    Only the model id is required.

    Raises:
        ValueError: When the model id is missing, or something given is not usable.
    """
    if not draft.model.strip():
        raise ValueError("A model id is required (--model)")
    entry: dict[str, object] = {"model": draft.model.strip()}
    if draft.token.strip():
        entry["token"] = draft.token.strip()
    if draft.name.strip():
        entry["display_model"] = draft.name.strip()
    if draft.url:
        entry["base_url"] = check_url(draft.url)
    elif draft.custom and draft.api is not Api.ANTHROPIC:
        raise ValueError("A custom provider needs an address (--url)")
    entry.update(draft.api.keys)
    if draft.chat and draft.api is Api.CHAT:
        entry["chat"] = True
    if draft.multimodal:
        entry["multimodal"] = True
    if draft.context_window is not None:
        entry["context_window"] = draft.context_window
    if draft.compact_percent is not None:
        entry["compact_percent"] = whole_if_whole(draft.compact_percent)
    if draft.temperature is not None:
        entry["temperature"] = whole_if_whole(draft.temperature)
    if draft.web_search:
        entry["web_search"] = True
        if draft.search_tool.strip():
            entry["web_search_name"] = draft.search_tool.strip()
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
        draft.chat = draft.api is Api.CHAT
        draft.given.add("api")
    if "--url" in flags:
        draft.url = check_url(flags["--url"], what="--url")
        draft.given.add("url")
    if "--model" in flags:
        draft.model = flags["--model"].strip()
    if "--token" in flags:
        draft.token = flags["--token"].strip()
        draft.given.add("token")
    if "--name" in flags:
        draft.name = flags["--name"].strip()
    if "--multimodal" in flags:
        draft.multimodal = True
    if "--web-search" in flags:
        draft.web_search = True
    if "--search-tool" in flags:
        draft.search_tool = flags["--search-tool"].strip()
        draft.web_search = True
    if "--context" in flags:
        draft.context_window = _flag(parse_tokens, flags["--context"], "--context")
    if "--compact" in flags:
        draft.compact_percent = _flag(parse_percent, flags["--compact"], "--compact")
    if "--temperature" in flags:
        draft.temperature = _flag(
            lambda text: parse_temperature(text, draft.api), flags["--temperature"], "--temperature"
        )
    return draft


def _flag(parse: Callable[[str], T], text: str, flag: str) -> T:
    """Read the value of a flag with ``parse``, naming the flag in what is wrong with it."""
    try:
        return parse(text)
    except ValueError as error:
        raise ValueError(f"{flag}: {error}") from None


def parse_tokens(text: str) -> int:
    """Read a size in tokens: ``128000``, ``128,000``, ``128k``, ``1m`` or ``1.5m``.

    Raises:
        ValueError: With a sentence saying how to write it, when it is not a size or is too small to be a window.
    """
    cleaned = re.sub(r"[\s,_]|tokens?$", "", text.strip().lower())
    found = re.fullmatch(r"(\d+(?:\.\d+)?)([km]?)", cleaned)
    if found is None:
        raise ValueError("write the size in tokens: 128000, 128k or 1m")
    tokens = round(float(found.group(1)) * {"": 1, "k": 1_000, "m": 1_000_000}[found.group(2)])
    if tokens < MIN_CONTEXT_WINDOW:
        raise ValueError(
            f"a context window is counted in tokens and is at least {MIN_CONTEXT_WINDOW:,}; "
            "write 200k for two hundred thousand"
        )
    return tokens


def parse_temperature(text: str, api: Api = Api.CHAT) -> float:
    """Read a sampling temperature: from 0 to 2, or from 0 to 1 for the Anthropic API.

    Raises:
        ValueError: With a sentence saying what is allowed.
    """
    limit = 1.0 if api is Api.ANTHROPIC else 2.0
    try:
        value = float(text.strip())
    except ValueError:
        raise ValueError(f"write the temperature as a number from 0 to {limit:g}, such as 0.2") from None
    if not 0.0 <= value <= limit:
        raise ValueError(f"the temperature is from 0 to {limit:g}" + (" for the Anthropic API" if limit == 1.0 else ""))
    return value


def parse_percent(text: str) -> float:
    """Read a share of the window: ``80`` or ``80%``, more than 0 and at most 100.

    Raises:
        ValueError: With a sentence saying what is allowed.
    """
    try:
        percent = float(text.strip().removesuffix("%").strip())
    except ValueError:
        raise ValueError("write a percentage of the window, such as 80") from None
    if not 0 < percent <= 100:
        raise ValueError("the percentage must be more than 0 and at most 100")
    return percent


def whole_if_whole(number: float) -> int | float:
    """Return ``80`` for ``80.0``, so the file reads ``compact_percent = 80`` and not ``80.0``."""
    return int(number) if float(number).is_integer() else number


def tokens_text(tokens: int) -> str:
    """Return a size the way a reader says it: ``128,000 tokens``."""
    return f"{tokens:,} tokens"


def limits_text(model: ModelInfo) -> str:
    """Return what a model's window and compaction setting come to, in one line."""
    percent = whole_if_whole(model.compact_percent)
    return (
        f"{tokens_text(model.context_window)} \u00b7 compressed at {percent}% ({model.compaction_max_tokens:,} tokens)"
    )


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
