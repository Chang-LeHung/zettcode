"""The line between a chat app and one ZettCode daemon.

A chat message becomes a prompt for a background agent, and the agent's answer goes back to the chat it
came from. The parts:

- ``state`` — what has to survive a restart: the IM login handshake, its credentials, the receive cursor, the
  id of the session the daemon runs, and the reply context of each chat. The IM client keeps none of this
  itself.
- ``guard`` — the one daemon the bridge owns: started on demand, started again when it goes away, left alone
  when it is running.
- ``link`` — the bridge's own session on the broker, so the daemon reads the message as a reader's and answers
  the bridge, which forwards the answer.
- ``bridge`` — the loop that ties them together, and everything that can go wrong in it.

``cli`` and ``worker`` make a command of it: ``zettcode-weixin`` logs in, then hands the connection to a
background process that runs the bridge.
"""

from __future__ import annotations

__all__: list[str] = []
