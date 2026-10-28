"""The web gateway: a browser front end for the background agents on this machine.

    zettcode-gateway              # then open the address it prints

A page lists the daemons (``zettcode daemon``) and the other sessions that are running, starts and stops daemons, and
lets a person talk to any of them as to a contact: what is typed is sent as a message from this gateway, and what the
session says comes back into the same conversation. The gateway is not an agent. It is one more session of the kind a
terminal is, with a person at it and no model of its own to run, and it reaches the agent through ``zettcode.sdk``
alone: starting and stopping daemons, who is registered, sending, and reading a stored conversation.

* :mod:`.chat` -- a stored conversation as chat items (no I/O);
* :mod:`.backend` -- what the gateway needs from the SDK, as an interface, and the one implementation that uses it;
* :mod:`.service` -- the gateway itself: threads, sending, daemons, unread marks and the events a page listens to;
* :mod:`.app` -- the web application: sign-in, the JSON endpoints, the event socket and the page;
* :mod:`.cli` -- the ``zettcode-gateway`` command.

``docs/internal/gateway.md`` has the design and the rules the tests pin.
"""

from __future__ import annotations

__all__ = ["app", "backend", "chat", "cli", "service", "settings"]
