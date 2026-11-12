# zettcode-code-agents

Gateway plugins that run **Codex** and **Claude Code** as external agents. Each is a persistent CLI session: the
session id is kept in `~/.zettcode/code-agents/` (or `$ZETTCODE_CODE_AGENTS_DIR`), so every message continues the same
conversation.

Install the package beside the gateway and restart it:

```bash
pip install zettcode-code-agents
```

The New page then offers **Codex** and **Claude Code**. Both register as `kind="external"` sessions; the gateway owner can add one to a
group, and it can then receive and write there.

The gateway only starts an agent. Where it works, how far it is trusted and which command it runs are this plugin's
settings, kept in its own file and read again **for every message**, so an edit applies to the next message of every
agent that is already running. Nothing has to be restarted.

## Settings

`~/.zettcode/code-agents/config.json` (or the file `$ZETTCODE_CODE_AGENTS_CONFIG` names). Every key is optional:

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
same setting, which wins over the default. `bin`, `args` and `resume_args` belong to one tool and are set only inside its
section.

| Key | Default | Meaning |
| --- | --- | --- |
| `cwd` | the gateway process's directory | The folder the CLI runs in. It must exist. |
| `permission` | `full` | How far the agent is trusted: `full`, `workspace` or `read`. |
| `timeout` | `900` | Seconds one turn may take before it is stopped. |
| `bin`, `args`, `resume_args` | see below | The command, per tool. |

### Permission

The default is `full`: the agent runs on its own and may do anything you may, because nobody is there to answer a
prompt. **That is the plugin's choice, not the gateway's**: starting the gateway with `--no-full` limits the daemons it
starts and does not limit these agents. Set `"permission"` to `workspace` or `read` to narrow them.

| `permission` | Codex | Claude Code |
| --- | --- | --- |
| `full` | `--dangerously-bypass-approvals-and-sandbox` | `--permission-mode bypassPermissions` |
| `workspace` | `--sandbox workspace-write` | `--permission-mode acceptEdits` |
| `read` | `--sandbox read-only` | `--permission-mode plan` |

`codex exec resume` takes no `--sandbox`, so a resumed Codex turn gets the same choice as
`-c sandbox_mode="workspace-write"` (or `"read-only"`).

A setting that cannot be used (invalid JSON, a folder that does not exist, an unknown level) fails that message with a
sentence naming the file and the key, in the agent's reply. Mend the file and send again.

## Commands

The commands are also configurable from the environment, which the `args` and `resume_args` keys override:

| Variable | Default |
| --- | --- |
| `ZETTCODE_CODEX_BIN` | `codex` |
| `ZETTCODE_CODEX_ARGS` | `exec --json --skip-git-repo-check {permission} {prompt}` |
| `ZETTCODE_CODEX_RESUME_ARGS` | `exec resume {session} --json {permission} {prompt}` |
| `ZETTCODE_CLAUDE_BIN` | `claude` |
| `ZETTCODE_CLAUDE_ARGS` | `{permission} -p {prompt} --output-format json --session-id {session}` |
| `ZETTCODE_CLAUDE_RESUME_ARGS` | `{permission} -p {prompt} --output-format json --resume {session}` |
| `ZETTCODE_CODE_AGENTS_CWD` | the gateway process's directory |
| `ZETTCODE_CODE_AGENTS_DIR` | `~/.zettcode/code-agents` |
| `ZETTCODE_CODE_AGENTS_CONFIG` | `config.json` in that directory |
| `ZETTCODE_CODE_AGENTS_QUEUE` | `4` turns waiting (read when the agent starts) |
| `ZETTCODE_CODE_AGENTS_TIMEOUT` | `900` seconds |

Arguments are split with `shlex`, never run by a shell, and receive `{prompt}`, `{session}` and `{cwd}`. The word
`{permission}` on its own stands for the arguments of the chosen level; a command you write without it is run exactly
as written, with no trust arguments added.

The CLIs must be installed and signed in for the user running the gateway.
