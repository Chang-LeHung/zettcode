"""What a person has made of a thread on this page: its name, its picture, and whether it is pinned or put away.

These are kept in the gateway's own folder by session id, because the sessions themselves know nothing of them. This is
state and its rules only: it asks the gateway nothing and tells the pages nothing, and a caller that has changed
something refreshes the views.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from pathlib import Path
from typing import Any

from .jsonfile import read_json, write_json

#: Where a page-visible name and picture for a thread are kept, by session id.
PROFILE_FILE = "profiles.json"

#: Keep a thread's profile this long after its session disappears from a refresh.
PROFILE_TTL = 24 * 60 * 60

#: The longest name, and the largest picture (as a data URL), a profile may hold.
MAX_NAME = 80
MAX_AVATAR = 300_000

#: Choices the person made about a conversation, which are kept until they undo them, however long it has been gone.
FLAGS = ("pinned", "archived")
CHOICES = set(FLAGS)


class ProfileError(ValueError):
    """A change to a profile that is refused; the message is the sentence a person is shown."""


class Profiles:
    """The profiles of the sessions the page has changed, by session id."""

    def __init__(self, directory: Path, clock: Callable[[], float]) -> None:
        self._path = directory / PROFILE_FILE
        self._clock = clock
        self._profiles = self._load()
        self._seen: dict[str, float] = {}

    def _load(self) -> dict[str, dict[str, str]]:
        data = read_json(self._path)
        if not isinstance(data, dict):
            return {}
        found: dict[str, dict[str, str]] = {}
        for session_id, value in data.items():
            if not isinstance(session_id, str) or not isinstance(value, dict):
                continue
            profile = {key: str(value[key]) for key in ("name", "avatar") if isinstance(value.get(key), str)}
            profile.update({key: "1" for key in FLAGS if value.get(key) == "1"})
            if profile:
                found[session_id] = profile
        return found

    def _save(self) -> None:
        write_json(self._path, self._profiles, ensure_ascii=False)

    def __contains__(self, session_id: object) -> bool:
        return session_id in self._profiles

    def get(self, session_id: str) -> Mapping[str, str]:
        """Return a session's profile, empty when it has none; a profile that is read counts as the session being here."""
        profile = self._profiles.get(session_id, {})
        if profile:
            self._seen[session_id] = self._clock()
        return profile

    def set_default_avatar(self, session_id: str, avatar: str) -> None:
        """Give a session that has none a picture, as a new agent has its type's.

        Raises:
            OSError: The profile could not be written; the picture is held until the next write all the same.
        """
        self._profiles[session_id] = {"avatar": avatar}
        self._save()

    def change(self, session_id: str, data: Mapping[str, Any]) -> None:
        """Apply what a page asked for to a session's profile and keep it; an empty value removes an override.

        Raises:
            ProfileError: A field is of the wrong kind or too large; nothing is changed.
            OSError: The profile could not be written.
        """
        profile = dict(self._profiles.get(session_id, {}))
        if "name" in data:
            name = data["name"]
            if not isinstance(name, str) or len(name) > MAX_NAME:
                raise ProfileError(f"name is a string of at most {MAX_NAME} characters")
            if name.strip():
                profile["name"] = name.strip()
            else:
                profile.pop("name", None)
        if "avatar" in data:
            avatar = data["avatar"]
            if not isinstance(avatar, str) or len(avatar) > MAX_AVATAR:
                raise ProfileError("avatar is a small image data URL")
            if avatar and not avatar.startswith("data:image/"):
                raise ProfileError("avatar is an image data URL")
            if avatar:
                profile["avatar"] = avatar
            else:
                profile.pop("avatar", None)
        for flag in sorted(CHOICES):
            if flag in data:
                if not isinstance(data[flag], bool):
                    raise ProfileError(f"{flag} is true or false")
                if data[flag]:
                    profile[flag] = "1"
                else:
                    profile.pop(flag, None)
        # Pinned and archived exclude each other: a conversation is either kept at the top or put away, and the last
        # one asked for wins (archiving unpins, pinning brings it back from the archive).
        if data.get("archived") is True:
            profile.pop("pinned", None)
        elif data.get("pinned") is True:
            profile.pop("archived", None)
        if profile:
            self._profiles[session_id] = profile
        else:
            self._profiles.pop(session_id, None)
        self._save()

    def forget_vanished(self, listed: Collection[str]) -> bool:
        """Drop the profiles of sessions that have left the list for a day, and say whether any was dropped.

        A name and a picture are kept for a day after a session leaves; a pin or an archive is a choice the person made
        about that conversation and is kept until they undo it.

        Raises:
            OSError: The profiles could not be written after some were dropped.
        """
        now = self._clock()
        vanished = [
            session_id
            for session_id, profile in self._profiles.items()
            if session_id not in listed
            and now - self._seen.get(session_id, now) > PROFILE_TTL
            and not profile.keys() & CHOICES
        ]
        for session_id in vanished:
            self._profiles.pop(session_id, None)
            self._seen.pop(session_id, None)
        if vanished:
            self._save()
        return bool(vanished)
