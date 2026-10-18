"""Text that comes from another process, and the words made from it.

A message is typed (or written by a model) in one terminal and painted in another, so it is cleaned
on the way in and again on the way out: no escape sequence that could move a cursor or retitle a
window, no stray control character, nothing a UTF-8 encoder would choke on. A title is reduced to one
short line, and a name to the characters the composer can type after an ``@``.

Nothing here knows about the wire or the roster; it is standard-library string handling, shared by
both.
"""

from __future__ import annotations

import re
import unicodedata

#: Control characters a message may not carry. Newline and tab stay (a message is prose and code),
#: and an escape sequence goes with the rest: text from another session is drawn in this terminal.
_CONTROLS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_SURROGATES = re.compile("[\ud800-\udfff]")
_ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[@-Z\\-_])")

#: The longest a name made by :func:`slug` may be.
SLUG_LENGTH = 32


def clean_text(text: str) -> str:
    """Return a message as it may be delivered: no escape sequences, no stray control characters.

    Lone surrogates become U+FFFD (they cannot be encoded), line endings become ``\\n``, and a
    sequence that would move the cursor or retitle the window is removed rather than shown: the
    sender is another program, and its words are painted in this terminal.
    """
    text = _SURROGATES.sub("\ufffd", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return _CONTROLS.sub("", _ANSI.sub("", text))


def clean_title(title: object, limit: int) -> str:
    """Return a title as the roster keeps it: one line, trimmed, at most ``limit`` characters.

    Anything that is not a string is an empty title, because a title is optional and a damaged one
    is not worth refusing a session over.
    """
    if not isinstance(title, str):
        return ""
    one_line = " ".join(clean_text(title).split())
    return one_line[:limit].rstrip()


def slug(title: str) -> str:
    """Return the part of a title that can follow an ``@``: lowercase ASCII words joined by ``-``.

    A mention is typed in the composer, whose reference syntax holds letters, digits and a few
    punctuation marks, so a title is reduced to those. Accents are folded (``café`` is ``cafe``);
    a title with no ASCII letters at all — Chinese, say — has no slug and the caller falls back
    to something else.
    """
    folded = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", folded).strip("-")[:SLUG_LENGTH].strip("-")


def folder_name(path: str) -> str:
    """Return the last part of a directory path, whichever way it is written: ``/a/b/`` and ``C:\\a\\b`` are both ``b``."""
    parts = [part for part in re.split(r"[\\/]+", path) if part and not part.endswith(":")]
    return parts[-1] if parts else ""


def short_id(session_id: str) -> str:
    """Return the first eight letters or digits of a session id: what a person can type of it."""
    return re.sub(r"[^a-z0-9]", "", session_id.lower())[:8] or "session"


def tail_id(session_id: str) -> str:
    """Return the last six letters or digits of a session id: the part of it that tells two sessions apart.

    Session ids are time-ordered, so the first eight characters are shared by every session started
    within about a minute of each other — which is exactly the case of a reader opening two terminals —
    and a name made from them would be the same for both. The end of the id is the random part.
    """
    return re.sub(r"[^a-z0-9]", "", session_id.lower())[-6:] or "session"
