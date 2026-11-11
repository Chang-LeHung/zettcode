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

## Commands

The commands are configurable without changing the package:

| Variable | Default |
| --- | --- |
| `ZETTCODE_CODEX_BIN` | `codex` |
| `ZETTCODE_CODEX_ARGS` | `exec --json --skip-git-repo-check {prompt}` |
| `ZETTCODE_CODEX_RESUME_ARGS` | `exec resume {session} --json {prompt}` |
| `ZETTCODE_CLAUDE_BIN` | `claude` |
| `ZETTCODE_CLAUDE_ARGS` | `-p {prompt} --output-format json --session-id {session}` |
| `ZETTCODE_CLAUDE_RESUME_ARGS` | `-p {prompt} --output-format json --resume {session}` |
| `ZETTCODE_CODE_AGENTS_CWD` | the gateway process's directory |
| `ZETTCODE_CODE_AGENTS_DIR` | `~/.zettcode/code-agents` |

Arguments are split with `shlex`, never run by a shell, and receive `{prompt}`, `{session}` and `{cwd}`.

The CLIs must be installed and signed in for the user running the gateway.
