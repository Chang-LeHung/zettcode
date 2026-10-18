"""ZettCode behind an HTTP API: the coding agent, driven by `zettcode.sdk`, one workspace per process.

The server is a thin layer: an endpoint says what to ask the agent and how to let a run answer for itself, and the
SDK does the work. It owns no model loop, no tools, and no session format, so a session begun here is one the
terminal can open afterwards, and the other way round.
"""

from __future__ import annotations

__version__ = "0.1.0"
