"""Talking to the other ZettCode sessions: the tools, the line to the broker, and later the inbox.

A part of the program that lives in a distribution of its own, found through the ``zettcode.agent`` entry point. The
runtime hands it the line to the broker by name (``MESSENGER``); without one it registers nothing, which is the case in
a program that never joins the sessions.
"""

from __future__ import annotations

from .messenger import Messenger
from .plugin import Messaging

__all__ = ["Messenger", "Messaging"]
