# External sessions

`zettcode.broker.external` is the high-level surface for a program that is not ZettCode but wants to join the
broker. It sits on `BrokerClient`, so the WebSocket, reconnection, registration, acknowledgements and limits stay in
one place; the protocol does not change.

## One-way: `ExternalPublisher`

```python
from zettcode.broker.external import ExternalPublisher

async with ExternalPublisher("ci") as publisher:
    await publisher.send("@build", "CI failed on main", mode="followup")
```

This is a `POST /messages` with the broker's owner token and no session key. The broker names the sender from
`ci`, marks the message `via="external"`, and does not put the sender in the roster: it cannot be replied to.

## Two-way: `ExternalSession`

```python
from zettcode.broker.external import ExternalSession
from zettcode.broker.models import Incoming, Receipt


class CIBot(ExternalSession):
    session_id = "ci-bot"
    title = "CI bot"

    async def on_message(self, message: Incoming) -> Receipt:
        if message.text == "status":
            await self.reply(message, "green")
        return Receipt(True, disposition="queued")


async def main() -> None:
    async with CIBot() as bot:
        await bot.send("@build", "CI failed", mode="followup")
```

The constructor also accepts `on_message=` instead of a subclass. A handler may return:

| Result | Ack |
| --- | --- |
| `Receipt(...)` | used as it is |
| `None` | `accepted=True, disposition="delivered"` |
| `str` | sent back to the sender, ack `queued` |
| awaitable | run after acking `queued`; it cannot refuse after that |

Without a handler, the default `on_message` puts messages on `session.inbox`; `await session.receive()` takes one.
The queue holds 1,000 messages by default and answers `busy` when full, so the broker holds the next one. A sync
handler runs on the receive loop and must return promptly; use an async handler for subprocess or network work.
An async handler is acked `queued` before it runs, so it cannot refuse the message — return a `Receipt` before
awaiting if the decision is a refusal.

The session is registered with `kind="external"` by default. It can exchange one-to-one messages and appears in the
roster, but the broker still denies groups, its own history, and the `direct` chat-window semantics.

A trusted gateway plugin can pass `kind="zettcode"`; then `send_group`, `join_group` and `groups` are available and
its messages use `via="agent"`. Only installed gateway code should use that kind.

## Multiple adapters

Each instance is a separate WebSocket and a separate roster entry:

```python
async with (
    CIBot(),
    ExternalSession("slack", "Slack bridge", on_message=slack_message),
):
    ...
```

A platform adapter keeps its own receive loop and calls `send`/`reply`; the broker only sees ordinary external
sessions.

## Errors

- `ExternalNotConnected`: no broker note, no connection, or a protocol the client does not speak.
- `ExternalConflict`: another process holds the same `session_id`.
- `SendError`: the broker or recipient refused a send; `reason` is the protocol's word.

The token in `broker.json` is the broker owner's credential, not a per-external-session credential. Only a trusted
local program should read it. `session_id` is a claim in the roster, not an authenticator: the broker does not
verify who registered a name, and `ExternalConflict` only means the name is taken right now.
