"""Talking to the other ZettCode sessions: the tools, the line to the broker, and later the inbox.

A part of the program that lives in a distribution of its own, found through the ``zettcode.plugin`` entry point. The
plugin builds the line to the broker from the configuration and provides it under :data:`~.messenger.SESSION_LINK`; a
front end that wants its own hands one over instead. With sessions switched off it builds none and registers nothing,
and the inbox is still provided for events a trigger or a program delivers.
"""

from __future__ import annotations

from .messenger import SESSION_LINK, Messenger
from .plugin import Messaging

__all__ = ["SESSION_LINK", "Messenger", "Messaging"]
