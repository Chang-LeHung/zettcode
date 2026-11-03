"""The background process that lets one ZettCode session send a message to another.

Every running session registers with one small local process, the *broker*. A session can then ask who else is
active, send a message to one of them, and be handed the messages sent to it; the shell turns a received message
into a turn, and the model gets a tool to send one. Anything else on the machine that holds the broker's token can
send one too.

The broker is a Starlette application served by uvicorn on a loopback port, and each part has one job:

* what is said and the limits on it — :mod:`.protocol`; who is registered — :mod:`.roster`; cleaning what comes from
  another process — :mod:`.text`;
* what the broker *decides* — :mod:`.hub`: the sessions, who a message is from, whether it may pass, who is told;
* how that is put on the web — :mod:`.web`: the routes, the token, the WebSocket of each session;
* the server's life — :mod:`.server`: bind, serve, say goodbye, stop when nobody needs it; and the process around
  it — :mod:`.runner`: the lock, the note, the signals (``python -m zettcode.broker``);
* what a session uses to reach it — :mod:`.client`, with :mod:`.finder` (find the broker, start it, replace an older
  one, using :mod:`.files` and :mod:`.process`) and :mod:`.models` (the words the rest of the application uses).

The client is imported by the shell with the rest of the application, and it only connects once the first frame is
up; the server only ever runs as ``python -m zettcode.broker``. Nothing here imports the shell, the agent or the
terminal, which :mod:`tests.test_structure` holds.
"""
