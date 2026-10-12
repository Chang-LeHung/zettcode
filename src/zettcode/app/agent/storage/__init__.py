"""Session storage: the conversation log, its metadata, and the agent plugin.

One folder per workspace, one folder per session, and everything about a session in its own::

    ~/.zettcode/sessions/<base64 workspace path>/
    ├── metadata.jsonl              <- the old index; read for sessions that predate their own file
    └── <session-id>/
        ├── data.jsonl              <- the append-only message tree
        ├── metadata.json           <- title and times: written on creation and rename only
        └── tool-output/            <- what a long shell command printed, kept for the model to read

:mod:`records` owns the conversation's record types and the parsed read model,
:mod:`metadata` owns the per-session file and the old log, and :mod:`store` puts them
behind one API: the persistence mixin and the :class:`SessionStore` plugin.
"""

from .metadata import MAX_TITLE, SessionInfo
from .records import STORE_FILE, MessageLine, Session, now
from .store import SessionPersistenceMixin, SessionStore, workspace_key

__all__ = [
    "MAX_TITLE",
    "MessageLine",
    "STORE_FILE",
    "Session",
    "SessionInfo",
    "SessionPersistenceMixin",
    "SessionStore",
    "now",
    "workspace_key",
]
