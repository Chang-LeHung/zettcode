# Codex 与 Claude Code

`zettcode-code-agents` 插件把 **Codex** 和 **Claude Code** 作为智能体运行，用 `@` 呼叫。每个各有一段命令行会话，会话 id 保存在
`~/.zettcode/code-agents/`（`$ZETTCODE_CODE_AGENTS_DIR` 可指向别的目录），所以每条消息都接着同一段对话。
插件只启动你已经装好的 CLI。

## 安装

```bash
pip install "zettcode[code-agents]"      # 或 zettcode[all]
zettcode gateway restart                 # 网关已在运行时
```

`codex` 和 `claude` 必须在运行网关的那个用户下安装并登录。它是网关插件，不会给终端增加任何东西。

## 启动一个

运行 `zettcode gateway start`，在浏览器里打开它打印的地址，点 **New**，选 **External agent**（外部智能体），挑
Codex 或 Claude Code，再点 **Start external agent**
（启动外部智能体）。智能体会出现在 Chats 里，你用 `@` 呼叫它，在页面里或终端会话里都行。
目前外部智能体不能拉进群聊：两个外部智能体会无休止地互相回复。旧版本留下的群里如果已有外部智能体，它仍在群里，
可能继续互相回复：打开该群的成员列表，把它移出去。
**New** 说没有安装外部智能体插件时，装好插件再重启网关。

## 信任与设置

::: warning 默认是 `full`
没有人回答提示，所以智能体自行运行，可以做你能做的任何事。这是插件的选择，不是网关的：`--no-full` 只限制网关启动的
daemon，**不**限制这些智能体。把 `"permission"` 设为 `workspace` 或 `read` 才能收窄。
:::

设置放在 `~/.zettcode/code-agents/config.json`（`$ZETTCODE_CODE_AGENTS_CONFIG` 可指向别的文件）。文件在每个回合开始时
重读，所以改动会作用到正在运行的智能体的下一条消息。所有键都是可选的：

| 键 | 默认值 | 含义 |
| --- | --- | --- |
| `cwd` | 网关进程所在的目录 | CLI 运行的目录，必须存在。 |
| `permission` | `full` | 信任程度：`full`、`workspace` 或 `read`。 |
| `timeout` | `900` | 一个回合最长多少秒，超过就停止。 |
| `bin`、`args`、`resume_args` | 各工具自己的命令 | 只写在 `"codex"` 或 `"claude"` 里面。 |

```json
{
  "permission": "workspace",
  "claude": { "bin": "/opt/bin/claude" }
}
```

`permission` 会变成 CLI 自己的参数：

| `permission` | Codex | Claude Code |
| --- | --- | --- |
| `full` | `--dangerously-bypass-approvals-and-sandbox` | `--permission-mode bypassPermissions` |
| `workspace` | `--sandbox workspace-write` | `--permission-mode acceptEdits` |
| `read` | `--sandbox read-only` | `--permission-mode plan` |

续接的 Codex 回合不能带 `--sandbox`，所以 `workspace` 和 `read` 改用 `-c sandbox_mode="workspace-write"`（或
`"read-only"`）。CLI 接受这个参数；它是否像 `--sandbox` 限制第一轮那样限制续接的那一轮，没有验证过，所以先发一条
消息让它尝试写到目录之外，确认被拒绝再依赖它。环境变量和命令参数见插件的
[README](https://github.com/Chang-LeHung/zettcode/tree/main/packages/zettcode-code-agents#readme)。

## 限制

- 这些 CLI 以启动网关的用户身份运行，拥有该用户的文件、凭据和网络。`full` 下它们拥有全部。
- 能登录网关的人就能启动并给这些智能体发消息。保管好 token，在监听本机以外的地址前先读
  [网页网关](/zh/guide/gateway#登录与权限)。
- 来自其他会话或群成员的消息会到达一个可以运行命令的智能体。群里有你无法控制的会话时，收窄 `permission`。
