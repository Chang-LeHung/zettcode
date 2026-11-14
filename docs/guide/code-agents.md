# Codex & Claude Code

The `zettcode-code-agents` plugin runs **Codex** and **Claude Code** as members of your sessions and groups. Each one is
a persistent command-line session: the session id is kept in `~/.zettcode/code-agents/` (or the folder
`$ZETTCODE_CODE_AGENTS_DIR` names), so every message continues the same conversation. Both register with the gateway as
`kind="external"` sessions.

The plugin only starts the tool you already have. It does not bring Codex or Claude Code with it.

## Install

```bash
pip install "zettcode[code-agents]"      # or zettcode[all]
zettcode gateway restart                 # if a gateway is already running
```

`zettcode[all]` includes it. The plugin is a gateway plugin: it adds nothing to the terminal.

The Codex CLI (`codex`) and the Claude Code CLI (`claude`) must be installed and signed in **for the user running the
gateway**.

## Start one

1. Run `zettcode gateway start` and open the page (see [Web gateway](/guide/gateway)).
2. Open **New** and choose the **External agent** tab.
3. Pick **Codex** or **Claude Code**. Give it a title if you want one.
4. Optionally type a group name in **Join group** (without the `#`).
5. Press **Start external agent**.

The agent appears in Chats. The gateway owner can add it to a group, and it can then receive and write there. You can
address it with `@` like any other session, from the page or from a terminal session. If **New** says no external agent
plugins are installed, install the plugin and restart the gateway.

## Where it works and how far it is trusted

The gateway only starts an agent. Where the agent works, how far it is trusted and which command it runs are the
plugin's own settings, in `~/.zettcode/code-agents/config.json` (or the file `$ZETTCODE_CODE_AGENTS_CONFIG` names). The
file is read again for **every message, when its turn starts**, so an edit applies to the next message of every agent that
is already running, a queued one included. Nothing has to be restarted. Every key is optional:

```json
{
  "cwd": "~/work",
  "permission": "full",
  "timeout": 900,
  "codex": { "cwd": "~/work/api", "permission": "workspace" },
  "claude": { "bin": "/opt/bin/claude" }
}
```

A key inside `"codex"` or `"claude"` wins over the same key at the top, which wins over the environment variable of the
same setting, which wins over the default.

| Key | Default | Meaning |
| --- | --- | --- |
| `cwd` | the gateway process's directory | The folder the CLI runs in. It must exist. A relative path is taken from the gateway process's folder, not from this file's. |
| `permission` | `full` | How far the agent is trusted: `full`, `workspace` or `read`. |
| `timeout` | `900` | Seconds one turn may take before it is stopped. |
| `bin`, `args`, `resume_args` | the tool's own command | The command, per tool. Set only inside `"codex"` or `"claude"`. |

A setting that cannot be used (invalid JSON, a folder that does not exist, an unknown level) fails that message with a
sentence naming the file and the key, in the agent's reply. Mend the file and send again. The command words, the
environment variables and the way arguments are split are in the plugin's
[README](https://github.com/Chang-LeHung/zettcode/tree/main/packages/zettcode-code-agents#readme).

## Permission

::: warning The default is `full`
Nobody is there to answer a prompt, so the agent runs on its own and may do anything you may. **That is the plugin's
choice, not the gateway's**: starting the gateway with `--no-full` limits the daemons it starts and does **not** limit
these agents. Set `"permission"` to `workspace` or `read` to narrow them.
:::

| `permission` | Codex | Claude Code |
| --- | --- | --- |
| `full` | `--dangerously-bypass-approvals-and-sandbox` | `--permission-mode bypassPermissions` |
| `workspace` | `--sandbox workspace-write` | `--permission-mode acceptEdits` |
| `read` | `--sandbox read-only` | `--permission-mode plan` |

### Codex `workspace` and `read`: the resumed run is not verified

`codex exec resume` takes no `--sandbox`. The plugin checked this against `codex-cli 0.160.1`, which answers "unexpected
argument". A resumed Codex turn is therefore given the same choice as a configuration override, `-c
sandbox_mode="workspace-write"` (or `"read-only"`). The CLI **accepts** that flag. Whether it **limits** a resumed run the
way `--sandbox` limits the first one has **not been verified**.

If you rely on `workspace` or `read` for Codex, send a second message that tries to write outside the folder and check
that it is refused before you trust it.

## Security

- The CLIs run as the user who started the gateway, with that user's files, credentials and network. The default
  `full` gives them all of it.
- Anyone who can sign in to the gateway can start these agents and message them. Keep the token private, and read
  [Web gateway](/guide/gateway#signing-in-and-who-may-use-it) before listening beyond this machine.
- A message from another session or from a group member reaches an agent that may run commands. Narrow `permission` if
  the group includes sessions you do not control.
