"""Session storage: the conversation log, its metadata, and the agent plugin.

One folder per workspace, one conversation file per session::

    ~/.zettcode/sessions/<base64 workspace path>/
    ├── metadata.jsonl              <- title and activity, folded on read
    └── <session-id>/
        └── data.jsonl              <- the append-only message tree

:mod:`records` owns the conversation's record types and the parsed read model,
:mod:`metadata` owns the per-workspace index file, and :mod:`store` puts them
behind one API: the persistence mixin and the :class:`SessionStore` plugin.
"""

from .metadata import MAX_TITLE, SessionInfo
from .records import MessageLine, Session, now
from .store import SessionPersistenceMixin, SessionStore, workspace_key

__all__ = [
    "MAX_TITLE",
    "MessageLine",
    "Session",
    "SessionInfo",
    "SessionPersistenceMixin",
    "SessionStore",
    "now",
    "workspace_key",
]
