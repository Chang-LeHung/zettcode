# Gateway external agents

An **external agent** is a session the gateway starts for an installed plugin. The plugin runs in the gateway
process; the session is an ordinary registered broker session, so Chats, the graph and groups see it like any other.

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
registration, and calls `join_group` when the page asked for one. The manager closes the session when it is removed
or the gateway stops.

`kind="zettcode"` is a **claim**, not a verified identity: the broker takes the session's word for it, and it is
equivalent to holding the broker token. Only a plugin the reader would trust with that token may use it. The code-agent
plugins stay `kind="external"` and still receive/write groups when the owner adds them. An ordinary external script that connects by itself stays `kind="external"`
and keeps the narrower permissions. A `kind="zettcode"` agent sends with `via="agent"`; `ExternalSession.send_group`
and `join_group` are available to it.

## Settings the page can choose

A plugin that lets the person decide something when starting an agent lists it in `AgentPlugin.fields`
(`AgentField(name, label, kind, choices, default, help, unrestricted)`) and overrides `create_with(session_id, title,
options)`. A plugin that does neither is unchanged: `create_with` falls back to `create`, and the type lists no fields.

- `kind` is `"text"`, `"choice"` (one of `choices`) or `"directory"`.
- The manager's `check_options` refuses a name the type does not list, a value that is not text, a choice that is not
  offered and anything past `MAX_OPTION` characters, and fills a field's `default` when the page sent none.
- The **gateway** (`Gateway._agent_options`) then applies what only it knows: a `directory` must exist and lie inside
  `--root` (`Gateway.workspace`, the check a daemon's workspace passes), and the field's `unrestricted` choice is
  refused when the gateway was started with `--no-full`. The page hides what the gateway would refuse, and the gateway
  refuses it again, because the page is not what keeps a sign-in from asking. A default is checked the same way as
  something the person typed.
- `zettcode-code-agents` offers `cwd` (a directory) and `permission` (`full`/`workspace`/`read`, `full` unrestricted).
  A choice becomes `CliAgent.overrides`, which `resolve(..., overrides=)` ranks above the file's tool section: it
  belongs to that one agent and is never written to the settings file.

## Page API

| Route | What it does |
| --- | --- |
| `GET /api/agents` | the installed types: `{agents: [{name, title, description, avatar, fields: [...]}]}` |
| `POST /api/agents` | `{kind, title?, group?, options?}` starts one and returns `{agent, thread}` |
| `DELETE /api/agents/{session_id}` | stops one |

The New page shows a form for the installed types. A created agent appears in Chats after the next refresh; its
messages are handled by the plugin's `on_message`.

## Lifecycle and failure

- A plugin that raises while loading is logged and skipped; it does not stop the gateway.
- A duplicate `session_id` is refused.
- A failed `connect` closes the partial session and is reported on the form.
- `group` is joined with the broker owner's credential, so only a trusted gateway-managed agent should use it.
