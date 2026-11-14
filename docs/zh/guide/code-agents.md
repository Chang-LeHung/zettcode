# Codex 与 Claude Code

`zettcode-code-agents` 插件把 **Codex** 和 **Claude Code** 作为你的会话和群的成员运行。每个都是一个持久的命令行会话：
会话 id 保存在 `~/.zettcode/code-agents/`（或 `$ZETTCODE_CODE_AGENTS_DIR` 指定的目录），所以每条消息都延续同一段对话。
两者都以 `kind="external"` 会话的身份向网关注册。

插件只负责启动你已经有的工具，不会替你安装 Codex 或 Claude Code。

## 安装

```bash
pip install "zettcode[code-agents]"      # 或 zettcode[all]
zettcode gateway restart                 # 如果网关已经在运行
```

`zettcode[all]` 已包含它。这是一个网关插件：它不会给终端增加任何东西。

Codex CLI（`codex`）和 Claude Code CLI（`claude`）必须在**运行网关的那个用户**下安装并登录。

## 启动一个

1. 运行 `zettcode gateway start`，打开页面（见[网页网关](/zh/guide/gateway)）。
2. 打开 **New**，选择 **External agent**（外部智能体）标签。
3. 选 **Codex** 或 **Claude Code**，需要的话填一个标题。
4. 可选：在 **Join group**（加入群组）里填一个群名（不带 `#`）。
5. 点 **Start external agent**（启动外部智能体）。

智能体会出现在 Chats 里。网关的主人可以把它加入群，之后它就能在群里收发消息。你可以像对其他会话一样用 `@` 呼叫它。
如果 **New** 页面提示没有安装外部智能体插件，请安装插件并重启网关。

## 它在哪里工作、被信任到什么程度

网关只负责启动智能体。智能体在哪里工作、被信任到什么程度、运行哪条命令，都是插件自己的设置，
放在 `~/.zettcode/code-agents/config.json`（或 `$ZETTCODE_CODE_AGENTS_CONFIG` 指定的文件）里。
这个文件会在**每条消息的回合开始时**重新读取，所以修改会作用到每个已在运行的智能体的下一条消息，排队中的也包括在内，不需要重启。所有键都是可选的：

```json
{
  "cwd": "~/work",
  "permission": "full",
  "timeout": 900,
  "codex": { "cwd": "~/work/api", "permission": "workspace" },
  "claude": { "bin": "/opt/bin/claude" }
}
```

`"codex"` 或 `"claude"` 里的键优先于顶层的同名键，顶层的键优先于同一设置的环境变量，环境变量又优先于默认值。

| 键 | 默认值 | 含义 |
| --- | --- | --- |
| `cwd` | 网关进程所在的目录 | CLI 运行的目录，必须存在。相对路径从网关进程的目录算起，不是从这个文件所在的目录。 |
| `permission` | `full` | 智能体被信任的程度：`full`、`workspace` 或 `read`。 |
| `timeout` | `900` | 一个回合最长允许的秒数，超过就被停止。 |
| `bin`、`args`、`resume_args` | 各工具自己的命令 | 每个工具的命令。只能写在 `"codex"` 或 `"claude"` 里面。 |

不能使用的设置（JSON 无效、目录不存在、级别未知）会让那条消息失败，在智能体的回复里给出一句话，指明文件和键名。改好文件再发一次即可。
命令参数、环境变量和参数的拆分方式见插件的
[README](https://github.com/Chang-LeHung/zettcode/tree/main/packages/zettcode-code-agents#readme)。

## 权限

::: warning 默认是 `full`
没有人来回答提示，所以智能体自行运行，可以做你能做的任何事。**这是插件的选择，不是网关的**：
用 `--no-full` 启动网关只会限制它启动的 daemon，**不会**限制这些智能体。把 `"permission"` 设为 `workspace` 或 `read` 才能收窄。
:::

| `permission` | Codex | Claude Code |
| --- | --- | --- |
| `full` | `--dangerously-bypass-approvals-and-sandbox` | `--permission-mode bypassPermissions` |
| `workspace` | `--sandbox workspace-write` | `--permission-mode acceptEdits` |
| `read` | `--sandbox read-only` | `--permission-mode plan` |

### Codex 的 `workspace` 与 `read`：续接的那一轮没有验证过

`codex exec resume` 不接受 `--sandbox`。插件对照 `codex-cli 0.160.1` 检查过，它回答 "unexpected argument"。
所以续接的 Codex 回合改用同样意思的配置覆盖 `-c sandbox_mode="workspace-write"`（或 `"read-only"`）。CLI **接受**这个参数，
但它是否像 `--sandbox` 限制第一轮那样**限制了**续接的那一轮，**没有验证过**。

如果你靠 `workspace` 或 `read` 来约束 Codex，请先再发一条消息，让它尝试写到目录之外，确认被拒绝，再信任它。

## 安全

- 这些 CLI 以启动网关的用户身份运行，拥有该用户的文件、凭据和网络。默认的 `full` 把这些全部交给它们。
- 能登录网关的人就能启动并给这些智能体发消息。请保管好 token，在监听本机以外的地址之前先读[网页网关](/zh/guide/gateway#登录与权限)。
- 来自其他会话或群成员的消息会到达一个可以运行命令的智能体。如果群里有你无法控制的会话，请收窄 `permission`。
