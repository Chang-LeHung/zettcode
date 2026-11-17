# Gateway external agents

An **external agent** is a session the gateway starts for an installed plugin. The plugin runs in the gateway
process; the session is an ordinary registered broker session, so Chats and the graph see it like any other. Groups
do not: the gateway keeps external agents out of them (see below).

This is not the same as a program that connects to the broker by itself (see `docs/internal/broker-external.md`).
A gateway agent is installed code, and the gateway owns its lifecycle.

## Plugin contract

A plugin is a class registered under the `zettcode.gateway.external` entry-point group:

```toml
[project.entry-points."zettcode.gateway.external"]
echo = "my_package:EchoAgent"
```

```python
from zettcode.broker.external import ExternalSession
from zettcode.broker.models import Incoming, Receipt
from zettcode.gateway.agents import AgentPlugin


class EchoSession(ExternalSession):
    async def on_message(self, message: Incoming) -> Receipt:
        await self.reply(message, message.text)
        return Receipt(True, disposition="delivered")


class EchoAgent(AgentPlugin):
    name = "echo"
    title = "Echo"
    description = "Answers with what it hears"

    def create(self, session_id: str, title: str) -> ExternalSession:
        return EchoSession(session_id, title, kind="zettcode")
```

`AgentPlugin.create` returns an **unconnected** `ExternalSession`; the gateway calls `connect`, waits for
registration. The manager closes the session when it is removed
or the gateway stops.

`AgentPlugin.probe()` is the gate before that: it returns an empty string when the agent can run, or the sentence that
says why not (and what to do). It runs in the gateway process (so a program is looked for on the PATH a turn will use),
must be quick, and must not start the program or check a login. `AgentManager._start` refuses with it before `create`,
so nothing is registered or put on the roster for an agent that cannot run, and `available()` carries
`runnable`/`reason` for the page to grey the type out. It is advice that can go stale: a turn that fails still answers
with its own sentence. A roster entry that cannot start is retried by the gateway's keeper every few seconds.

`kind="zettcode"` is a **claim**, not a verified identity: the broker takes the session's word for it, and it is
equivalent to holding the broker token. Only a plugin the reader would trust with that token may use it. The code-agent
plugins stay `kind="external"`. An ordinary external script that connects by itself stays `kind="external"`
and keeps the narrower permissions. A `kind="zettcode"` agent sends with `via="agent"`; `ExternalSession.send_group`
and `join_group` stay on the contract, but the gateway does not call them (below).

## No external agent in a group

The gateway refuses to put an external agent in a group: `invite_group`, `create_group` and `create_agent` with a
`group` answer 400 `external_in_group`, and the page neither lists one nor has a Join-group field. "External" is a
session the broker lists as `kind="external"` (so an offline `external:<handle>` too) **or** one the manager knows by
type (`agents.kind_of`, which also covers a roster agent that is not connected, or a plugin agent registered as
`kind="zettcode"`). Why: the broker zeroes the hop count of a message from a `kind="external"` sender
(`protocol.py`), so `MAX_HOPS` does not bound two of them answering each other; only the throttle does. A `zettcode`
agent sends as `via="agent"` and is bounded, but the rule is one for both, so it need not know which is which.

The rule guards the *add* paths only. A membership made before it (the old "Start & invite" and Join-group field)
stays; nothing removes it, because taking a member out of a group is the owner's act. Remove one with
`DELETE /api/groups/{name}/members/{id}` or from the group's member list.

## Page API

| Route | What it does |
| --- | --- |
| `GET /api/agents` | the installed types: `{agents: [{name, title, description}]}` |
| `POST /api/agents` | `{kind, title?}` starts one and returns `{agent, thread}`; a `group` is refused |
| `DELETE /api/agents/{session_id}` | stops one |

The New page shows a form for the installed types. A created agent appears in Chats after the next refresh; its
messages are handled by the plugin's `on_message`.

## Lifecycle and failure

- A plugin that raises while loading is logged and skipped; it does not stop the gateway.
- A duplicate `session_id` is refused.
- A failed `connect` closes the partial session and is reported on the form.
- A `group` in the request is refused (see "No external agent in a group").
