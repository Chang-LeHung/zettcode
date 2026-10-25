"""``@`` references: resources a draft can pull into one message.

A mention is a token like ``@code-review`` typed in the composer. A provider
owns one kind of resource — the builtin one is skills — and both lists
candidates for the completion menu and expands a token into the text the model
should see. The draft the user typed stays the message that is stored and
shown; the expansion is carried as a message attribute, so a session loaded
later restores the original text instead of the injected resource.
"""

from __future__ import annotations

import os
import re
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from heapq import nsmallest
from pathlib import Path
from time import monotonic
from typing import TypeAlias

from zett_agent.extensions.skill import SkillExtension

from zettcode.broker.text import folder_name
from zettcode.config import ZettCodeConfig
from zettcode.registry import Provider, Registry
from zettcode.relay import Peer

#: One mention token: an ``@`` at a word boundary, then a name. A name is what a
#: skill is called (lowercase words) or where a file lives (``src/app.py``), so it
#: holds path punctuation as well; it starts with a letter, a digit, or an
#: underscore, which is what keeps ``@/`` and a trailing ``@`` out. The lookbehind
#: keeps an email address or a second ``@`` from matching.
MENTION = re.compile(r"(?<![\w@])@([A-Za-z0-9_][A-Za-z0-9_./-]*)")


@dataclass(frozen=True, slots=True)
class Mention:
    """One resource a draft can reference.

    Attributes:
        token: Text as typed, e.g. ``@code-review``.
        kind: Provider that owns the resource, e.g. ``"skill"``.
        name: Resource name without the ``@``.
        description: One line shown by the completion menu.
    """

    token: str
    kind: str
    name: str
    description: str


class MentionProvider(Provider[Mention], ABC):
    """One kind of ``@`` resource: what it offers and what it injects."""

    #: Short name shown in the completion menu's type column, e.g. ``"skill"``.
    kind: str

    @abstractmethod
    def candidates(self, query: str) -> Sequence[Mention]:
        """Return the resources whose name matches ``query`` (without the ``@``)."""

    @property
    def items(self) -> Sequence[Mention]:
        """Return every resource this provider offers."""
        return self.candidates("")

    @abstractmethod
    def expand(self, name: str) -> str | None:
        """Return the text one resource injects, or ``None`` when it is unknown."""

    def rename(self, name: str) -> str | None:
        """Return the words the model reads in place of ``@name``, or ``None`` to leave the token as typed.

        Most references are meaningful to the model as they are (a path, a skill's name). One that is not —
        the name of another session — is replaced, so the model is not left holding a word it must guess at.
        """
        return None


class MentionRegistry(Registry[Mention]):
    """The providers a draft is resolved against, in registration order."""

    def __init__(self, providers: Sequence[MentionProvider] = ()) -> None:
        """Keep the providers; the first to claim a name wins a duplicate."""
        super().__init__(providers)

    def candidates(self, query: str) -> tuple[Mention, ...]:
        """Return every resource whose name matches ``query`` (which has no ``@``).

        Each provider is asked for the query rather than handed every item it has:
        a draft is completed on every keystroke, and the file provider holds
        thousands of names it would otherwise build a ``Mention`` for each time.
        An earlier provider still wins a duplicate name.
        """
        seen: set[str] = set()
        merged: list[Mention] = []
        for provider in self.mention_providers:
            for mention in provider.candidates(query):
                if mention.name in seen:
                    continue
                seen.add(mention.name)
                merged.append(mention)
        return tuple(merged)

    @property
    def mention_providers(self) -> tuple[MentionProvider, ...]:
        """Return the providers as the ``@``-specific type that can expand tokens."""
        return tuple(provider for provider in self.providers if isinstance(provider, MentionProvider))

    def expand_token(self, token: str) -> str | None:
        """Resolve one typed ``@`` token into the text it contributes, if any.

        The shell gets the tokens from the composer's parts rather than scanning
        the draft, so this is handed ``"@name"`` exactly as it was written.
        """
        name = token[1:] if token.startswith("@") else token
        for provider in self.mention_providers:
            block = provider.expand(name)
            if block is not None:
                return block
        return None

    def rename_token(self, token: str) -> str | None:
        """Return the words the model reads in place of one typed token, from the provider that owns it.

        The owner is the first provider that knows the name, which is the one :meth:`expand_token` asks:
        a session and a file with one name are the session.
        """
        name = token[1:] if token.startswith("@") else token
        for provider in self.mention_providers:
            if provider.expand(name) is not None:
                return provider.rename(name)
        return None


class SkillMentions(MentionProvider):
    """Skills discovered from the configured roots, named for the model to load."""

    kind = "skill"

    def __init__(self, config: ZettCodeConfig) -> None:
        """Discover skills once, the same way the agent's skill extension does."""
        self._skills = {skill.name: skill for skill in SkillExtension(config.skill_search_roots()).skills}

    def candidates(self, query: str) -> Sequence[Mention]:
        """List the discovered skills whose name starts with ``query``."""
        return tuple(
            Mention(token=f"@{skill.name}", kind=self.kind, name=skill.name, description=skill.description)
            for skill in self._skills.values()
            if skill.name.startswith(query)
        )

    def expand(self, name: str) -> str | None:
        """Name the skill and leave loading its instructions to the model.

        The system prompt already catalogs every skill, and ``read_skill`` loads
        the file, so the message only has to say which one the user meant;
        inlining the body would spend context on instructions that may not be
        needed.
        """
        skill = self._skills.get(name)
        if skill is None:
            return None
        return (
            f'Use the "{skill.name}" skill: call read_skill(name="{skill.name}") '
            "if its instructions are useful and not already in context."
        )


class SessionMentions(MentionProvider):
    """The other ZettCode sessions that are running, addressed by the name they are listed under.

    A session named anywhere in a draft is a reference like any other: the model reads ``session "name"``
    and is told how to reach that session, and decides for itself whether the request calls for a message.
    The shell sends nothing itself (see :mod:`zettcode.app.ui.messaging`).

    Candidates are read from what the connection last reported — a list in memory — and never from
    the broker: completion runs on every keystroke after an ``@``.
    """

    kind = "session"

    def __init__(self, peers: Callable[[], Sequence[Peer]]) -> None:
        """Offer whichever sessions ``peers`` returns when asked.

        Args:
            peers: The other sessions as of now; called for every query, so it must not block.
        """
        self._peers = peers

    def candidates(self, query: str) -> Sequence[Mention]:
        """List the sessions ``query`` could mean, the likeliest first.

        A reader looks for a session by what they remember of it, which is its name, what it was about,
        the folder it works in, or the start of its id — so any of those matches, with a session whose
        *name* starts with the query before one that only mentions it elsewhere. The token offered is
        always the name, because that is what can be sent to.
        """
        lowered = query.lower()
        ranked: list[tuple[int, int, Peer]] = []
        for order, peer in enumerate(self._peers()):
            if peer.handle.lower().startswith(lowered):
                ranked.append((0, order, peer))
            elif (
                lowered in peer.handle.lower() or lowered in peer.title.lower() or lowered in self._folder(peer).lower()
            ):
                ranked.append((1, order, peer))
            elif len(lowered) >= 4 and peer.session_id.lower().startswith(lowered):
                ranked.append((2, order, peer))
        return tuple(
            Mention(token=f"@{peer.handle}", kind=self.kind, name=peer.handle, description=self._describe(peer))
            for _, _, peer in sorted(ranked, key=lambda item: item[:2])
        )

    @staticmethod
    def _folder(peer: Peer) -> str:
        """Return the last part of the directory the session works in."""
        return folder_name(peer.workspace)

    @classmethod
    def _describe(cls, peer: Peer) -> str:
        """Return the menu's line for a session: what it is about, whether it is working, where it is."""
        parts = [peer.title or "untitled"]
        if peer.status != "idle":
            parts.append(peer.status)
        folder = cls._folder(peer)
        if folder:
            parts.append(folder)
        return " \u00b7 ".join(parts)

    def rename(self, name: str) -> str | None:
        """Put ``session "work"`` where the reader typed ``@work``: the model has no use for the ``@``."""
        return f'session "{name}"' if self._find(name) is not None else None

    def _find(self, name: str) -> Peer | None:
        """Return the session called ``name`` among those running now."""
        return next((peer for peer in self._peers() if peer.handle == name), None)

    def expand(self, name: str) -> str | None:
        """Tell the model what the reader's ``@`` meant and how to reach that session.

        Nothing is sent from here: the model is told which session the words mean and how to reach it, and
        decides for itself whether the request calls for a message. A draft that begins with the name is no
        different from one that names the session inside a sentence.
        """
        peer = self._find(name)
        if peer is None:
            return None
        where = f" in {peer.workspace}" if peer.workspace else ""
        about = f' It is titled "{peer.title}".' if peer.title else ""
        return (
            f'In the message above, `session "{name}"` is what the user wrote as @{name}. In ZettCode an @ before a '
            f"name means another ZettCode session that is running right now, not a file or a skill. This one works{where}.{about}\n"
            f"When the user's message is addressed to that session — the @ begins the message — what follows the name "
            f"is the message to pass on. When the session is only mentioned, decide whether the request is for it. "
            f'To send, call the send_message tool: send_message(to="{peer.session_id}", message=...). Write the '
            f"message so the other session can act on it without having seen this conversation. If the request is only "
            f"about the session (what it is doing, where it is), list_sessions answers that. Do not send anything the "
            f"user did not ask you to pass on."
        )


#: Directories ``@`` never offers files from: version control, the dependency
#: trees, and the caches. They are where a repository keeps things nobody wants
#: to reference in a message, and walking them is most of what a listing costs.
SKIP_DIRECTORIES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        "site-packages",
        "dist",
        "build",
        "target",
    }
)

#: Files offered in one listing. A repository larger than this is listed up to
#: here rather than not at all, and the walk stops as soon as the cap is reached.
MAX_FILES = 4000

#: Candidates returned for one query. The menu shows a handful; the rest would be
#: scrolled past, and building them on every keystroke is the cost this bounds.
MAX_CANDIDATES = 40

#: How long a listing is reused. Long enough that typing a path walks the tree
#: once instead of once a keystroke, short enough that a file made in the
#: meantime shows up in the menu.
LISTING_SECONDS = 15.0

#: One listed file: its path, the path lowercased, and its name lowercased. Built
#: once per walk, because the menu is filtered again on every keystroke and a
#: listing of thousands would otherwise be lowercased and split every time.
ListedFile: TypeAlias = tuple[str, str, str]


class FileMentions(MentionProvider):
    """Files in the workspace, so a draft can point at one by path.

    The listing is not the completeness of ``ls``: it is what a reader is likely to
    type after an ``@``, so the version control and dependency directories are
    skipped and there is a cap. What a token expands to is a sentence naming the
    path, not the file's contents: the model has ``read_file``, and inlining a
    file nobody needs would spend context on it.
    """

    kind = "file"

    def __init__(self, workspace: Path, *, clock: Callable[[], float] = monotonic) -> None:
        """List ``workspace`` when something first asks, and remember it for a while.

        Args:
            workspace: Directory to walk; the paths offered are relative to it.
            clock: Time source, injectable so a test can age the listing.
        """
        self.workspace = workspace
        self._clock = clock
        self._files: tuple[ListedFile, ...] = ()
        self._listed_at: float | None = None

    def _listing(self) -> tuple[ListedFile, ...]:
        """Return the workspace's files, walking it again when the listing is stale.

        The walk happens on the first keystroke after an ``@``, so it is bounded three
        ways: the directories nobody references are never entered, the walk stops at
        :data:`MAX_FILES`, and the result is reused for :data:`LISTING_SECONDS`.
        """
        now = self._clock()
        if self._listed_at is not None and now - self._listed_at < LISTING_SECONDS:
            return self._files
        found: list[ListedFile] = []
        for root, directories, names in os.walk(self.workspace):
            directories[:] = sorted(
                name for name in directories if name not in SKIP_DIRECTORIES and not name.startswith(".")
            )
            base = Path(root)
            for name in sorted(names):
                path = (base / name).relative_to(self.workspace).as_posix()
                found.append((path, path.lower(), name.lower()))
                if len(found) >= MAX_FILES:
                    break
            if len(found) >= MAX_FILES:
                break
        self._files = tuple(found)
        self._listed_at = now
        return self._files

    def candidates(self, query: str) -> Sequence[Mention]:
        """Offer the files whose path matches ``query``, the likeliest ones first.

        A path that starts with what was typed, or whose file name does, comes
        before one that merely contains it: ``@cli`` should offer
        ``cli.py`` before ``src/zettcode/tui/render/cli_helper.py``.
        """
        lowered = query.lower()
        ranked: list[tuple[int, int, str]] = []
        for path, path_lower, name_lower in self._listing():
            if path_lower.startswith(lowered) or name_lower.startswith(lowered):
                rank = 0
            elif lowered in path_lower:
                rank = 1
            else:
                continue
            ranked.append((rank, len(path), path))
        # Only the rows that will be shown are ordered: a one-letter query can match a
        # listing of thousands in hundreds of places, and sorting all of those is work
        # the menu never shows.
        return tuple(
            Mention(token=f"@{path}", kind=self.kind, name=path, description=described)
            for _, _, path in nsmallest(MAX_CANDIDATES, ranked)
            if (described := self._describe(path)) is not None
        )

    def _describe(self, path: str) -> str | None:
        """Return the menu's one line for a file: how big it is, or ``None`` if it is gone.

        Asking the file also drops one that was deleted since the listing, which is
        the one way a cached listing goes wrong while it is being typed into.
        """
        try:
            size = (self.workspace / path).stat().st_size
        except OSError:
            return None
        if size < 1024:
            return f"{size} B"
        if size < 1024 * 1024:
            return f"{size / 1024:.1f} kB"
        return f"{size / (1024 * 1024):.1f} MB"

    def expand(self, name: str) -> str | None:
        """Name the path for the model, which reads it with a tool if it matters.

        A directory is named as one, because the tool to reach for is not
        ``read_file`` and saying so is cheaper than the model finding out.
        """
        target = self.workspace / name
        if target.is_dir():
            return (
                f'The reader pointed at the directory "{name}" in the workspace; '
                "list or search it with the file tools when it matters."
            )
        if not target.is_file():
            return None
        return (
            f'The reader pointed at the file "{name}" in the workspace; '
            "read it before answering when its contents matter."
        )
