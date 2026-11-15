# Codex & Claude Code

The `zettcode-code-agents` plugin runs **Codex** and **Claude Code** as group members. Each keeps one command-line
session, whose id lives in `~/.zettcode/code-agents/` (`$ZETTCODE_CODE_AGENTS_DIR` names another folder), so every
message continues the same conversation. The plugin only starts the CLI you already have.

## Install

```bash
pip install "zettcode[code-agents]"      # or zettcode[all]
zettcode gateway restart                 # if a gateway is already running
```

The `codex` and `claude` CLIs must be installed and signed in for the user who runs the gateway. The plugin is a
gateway plugin: it adds nothing to the terminal.

## Start one

Open `zettcode gateway start` in a browser, press **New**, choose the **External agent** tab, pick Codex or Claude Code,
optionally type a group name in **Join group** (without the `#`), and press **Start external agent**. The agent appears
in Chats, and you address it with `@` from the page or from a terminal session. If **New** says no external agent
plugin is installed, install it and restart the gateway.

## Trust and settings

::: warning The default is `full`
Nobody answers a prompt, so the agent runs on its own and may do anything you may. That is the plugin's choice, not the
gateway's: `--no-full` limits the daemons the gateway starts and does **not** limit these agents. Set `"permission"` to
`workspace` or `read` to narrow them.
:::

Settings are in `~/.zettcode/code-agents/config.json` (`$ZETTCODE_CODE_AGENTS_CONFIG` names another file). The file is
read again at the start of every turn, so an edit applies to the next message of an agent that is already running.
Every key is optional:

| Key | Default | Meaning |
| --- | --- | --- |
| `cwd` | the gateway process's directory | The folder the CLI runs in. It must exist. |
| `permission` | `full` | How far the agent is trusted: `full`, `workspace` or `read`. |
| `timeout` | `900` | Seconds one turn may take before it is stopped. |
| `bin`, `args`, `resume_args` | the tool's own command | Per tool, set only inside `"codex"` or `"claude"`. |

```json
{
  "permission": "workspace",
  "claude": { "bin": "/opt/bin/claude" }
}
```

`permission` becomes the CLI's own flags:

| `permission` | Codex | Claude Code |
| --- | --- | --- |
| `full` | `--dangerously-bypass-approvals-and-sandbox` | `--permission-mode bypassPermissions` |
| `workspace` | `--sandbox workspace-write` | `--permission-mode acceptEdits` |
| `read` | `--sandbox read-only` | `--permission-mode plan` |

A resumed Codex turn cannot take `--sandbox`, so for `workspace` or `read` the plugin passes
`-c sandbox_mode="workspace-write"` or `"read-only"` instead. The CLI accepts that flag; whether it limits a resumed
run the way `--sandbox` limits the first one is not verified, so send a message that tries to write outside the folder
before you rely on it. The environment variables and the command words are in the plugin's
[README](https://github.com/Chang-LeHung/zettcode/tree/main/packages/zettcode-code-agents#readme).

## Limits

- The CLIs run as the user who started the gateway, with that user's files, credentials and network. At `full` they
  have all of it.
- Anyone who can sign in to the gateway can start these agents and message them. Keep the token private, and read
  [Web gateway](/guide/gateway#signing-in-and-who-may-use-it) before listening beyond this machine.
- A message from another session or a group member reaches an agent that may run commands. Narrow `permission` when the
  group holds sessions you do not control.
