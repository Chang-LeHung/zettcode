"""Session storage: the conversation log, its metadata, and the agent plugin.

One folder per workspace, one folder per session, and everything about a session in its own::

    ~/.zettcode/sessions/<workspace path, levels joined with ->/
    ├── workspace.txt               <- the path the folder belongs to (see :mod:`layout`)
    ├── metadata.jsonl              <- the old index; read for sessions that predate their own file
    ├── usage.json                  <- what ``/usage`` has counted so far, so it reads only what is new (see :mod:`ledger`)
    └── <session-id>/
        ├── data.jsonl              <- the append-only message tree
        ├── metadata.json           <- title and times: written on creation and rename only
        ├── session.lock            <- held by the process that has the session open (see :mod:`locks`)
        └── tool-output/            <- what a long shell command printed, kept for the model to read

:mod:`records` owns the conversation's record types and the parsed read model,
:mod:`metadata` owns the per-session file and the old log, and :mod:`store` puts them
behind one API: the persistence mixin and the :class:`SessionStore` plugin. :mod:`layout` names the
workspace folder, and renames one that an older version named with base64.
"""

from .layout import find_workspace, legacy_workspace_key, open_workspace, workspace_key
from .locks import LOCK_FILE, LOCKED_MESSAGE, NoLocks, SessionGuard, SessionLocked, SessionLocks
from .metadata import MAX_TITLE, SessionInfo
from .records import STORE_FILE, MessageLine, Session, now
from .store import SessionPersistenceMixin, SessionStore

__all__ = [
    "LOCKED_MESSAGE",
    "LOCK_FILE",
    "MAX_TITLE",
    "MessageLine",
    "STORE_FILE",
    "NoLocks",
    "Session",
    "SessionGuard",
    "SessionInfo",
    "SessionLocked",
    "SessionLocks",
    "SessionPersistenceMixin",
    "SessionStore",
    "find_workspace",
    "legacy_workspace_key",
    "now",
    "open_workspace",
    "workspace_key",
]
