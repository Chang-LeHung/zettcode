"""Background agents: a session with nobody at the keyboard, which other sessions reach with ``send_message``.

    zettcode daemon spawn          # start one; it prints the session id it is messaged by
    zettcode daemon list           # every daemon on this machine, alive or dead
    zettcode daemon kill <id>      # stop one, and remove its record; the session stays

A daemon is an ordinary session — stored where every session is, resumable in the terminal afterwards — plus a
record of its process under ``~/.zettcode/daemon/<workspace>/<session-id>/`` (:mod:`.state`) and the loop that
answers messages (:mod:`.run`). :mod:`.process` starts it detached and stops it; :mod:`.cli` is the command.
"""

from __future__ import annotations

__all__ = ["cli", "process", "run", "state"]
