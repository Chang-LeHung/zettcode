# Skills 与 MCP

有两种方式让 ZettCode 学会它本身没有的东西：你自己写的 **skills**，和现成的 **MCP 服务器**。
skills 提供可复用的指令，MCP 服务器提供额外工具。两者默认启用，但需要本地文件或服务器
定义才有内容可加载。

## Skills

一个 skill 就是一个目录，里面放一份带 name 和 description 的 `SKILL.md`：

```
~/.zettcode/skills/
└── code-review/
    └── SKILL.md
```

```md
---
name: code-review
description: Review a diff with the team checklist
---

把 diff 读两遍。先看错误处理，再看命名，最后看测试。
发现的问题按严重程度从高到低列出来。
```

进入模型的只是**目录** —— 名字和描述，仅此而已。正文只有在模型判断自己需要时才被读取，这也是
skills 再多也不会把上下文占满的原因。

两种发现方式：

| 位置 | 给谁用 |
| --- | --- |
| `~/.zettcode/skills/` | 你自己，在所有项目里都生效。 |
| `[skills] roots` | 项目或团队：`roots = [".zettcode/skills"]` 按工作区解析。 |

名字冲突时前面的根目录优先，配置的根目录排在自带的目录之前。`[skills] enabled = false` 可以
关掉发现。

### 用起来

在草稿里输入 `@` 就能引用一个 skill：

> 用 @code-review 帮我审一下刚才的改动

菜单会列出找到的 skills。被存下来的消息就是你打的那句，所以之后恢复会话看到的是
`@code-review`，而不是一大段指令；模型只被告知在需要时去加载这个 skill。

### 例子：安装自己的审阅 skill

1. 创建 `~/.zettcode/skills/code-review/` 目录。
2. 把上面的示例保存为目录中的 `SKILL.md`，保留 `---` 和 `name`、`description` 两个字段。
3. 重启 ZettCode，输入 `@code`，从菜单中选择 `code-review`。
4. 发送“用 @code-review 审阅当前 diff，先不要修改文件。”

引用时用名字，不是绝对路径。如果菜单没有出现，检查目录和文件的拼写，以及是否配置了
`[skills] enabled = false`。添加 skill 不等于安装工具：正文可以指导模型使用已有工具，
但不会凭空创建新工具。

想让 skill 随项目提交，可以放在 `<工作区>/.zettcode/skills/code-review/SKILL.md`，
再把下面的段落加到 `config.toml`：

```toml
[skills]
roots = [".zettcode/skills"]
```

项目内的 skill 目录需要显式配置，并不会自动搜索。使用别人提供的 skill 前，先阅读正文，
就像检查交给同事的任务说明一样。

## MCP 服务器

MCP 服务器会发布工具。ZettCode 从 `~/.zettcode/mcp.json`（或 `[mcp] config` 指向的位置）读取，
把每个工具注册成 `<服务器名>__<工具名>`，和自带工具放在一起。

### 例子：本地浏览器服务器

以 Chrome DevTools 为例，先安装能提供 `npx` 的 Node.js 和 Google Chrome，
再把这份 **JSON** 保存到 `~/.zettcode/mcp.json`：

```json
{
  "servers": {
    "browser": {
      "command": "npx",
      "args": ["-y", "chrome-devtools-mcp@latest"]
    }
  }
}
```

重启后可以发送：

> 用浏览器工具打开 `http://localhost:3000`，检查是否有控制台错误。

你的应用应该已经在这个 URL 运行。服务器是外部程序，不是 ZettCode 自带的包，第一次启动
可能需要下载。支持的 Node.js 版本和浏览器选项见它的
[安装说明](https://github.com/ChromeDevTools/chrome-devtools-mcp)。
需要可控版本时，用自己审阅过的版本替代 `@latest`。

### 例子：远程 HTTP 服务器

如果已有服务提供 MCP 接口，填写它的实际地址：

```json
{
  "servers": {
    "docs": {
      "type": "streamable-http",
      "url": "http://127.0.0.1:9000/mcp"
    }
  }
}
```

这个 URL 只是示例，需要自己启动服务器或替换地址。想同时使用两个服务器，把 `browser`
和 `docs` 放进同一个 `servers` 对象，不能直接拼接两份 JSON。JSON 必须使用双引号，
不支持注释和末尾多余的逗号。

`mcpServers` 是 `servers` 的另一种写法；一个服务器要么是 streamable HTTP 的 `url`（可带
`headers`），要么是 stdio 的 `command`（可带 `args`、`env`、`cwd`）。

| 服务器参数 | 含义 | 例子 |
| --- | --- | --- |
| `command` | 本地 stdio 服务器的可执行程序，启动进程必须能找到它。 | `"npx"` |
| `args` | 独立的命令参数组成的数组。 | `["-y", "chrome-devtools-mcp@latest"]` |
| `env` | 传给服务器的环境变量值。 | `{ "API_KEY": "your-server-key" }` |
| `cwd` | 本地服务器的工作目录。 | `"/absolute/path/to/project"` |
| `url` | 远端 MCP 接口，不是普通网页地址。 | `"http://127.0.0.1:9000/mcp"` |
| `headers` | 远端服务器需要的 HTTP 请求头。 | `{ "Authorization": "Bearer your-server-key" }` |

本地 stdio 使用 `command`，HTTP 使用 `"type": "streamable-http"` 和 `url`，
它们是两种不同的传输方式。

::: warning 外部工具需要信任
MCP 服务器使用进程本身的权限，也可能提供产生副作用的工具。ZettCode 的 shell 审批不是
所有 MCP 工具的沙箱。启用前先确认服务器来源和能力，`env` 或 `headers` 中的密钥不要提交到 Git。
:::

没有这个文件就是没有东西可加载，于是一次没配置 MCP 的运行完全不会带上 MCP 相关指令 —— 而不是
放进一条“没有可加载内容”的系统消息。`[mcp] enabled = false` 关掉这个扩展；启动失败的服务器会
被指名报出来，不会让一个挂掉的接入点看起来像请求卡住。

::: tip 话多的服务器弄不坏画面
stdio 服务器会把启动横幅写到 stderr。ZettCode 占用终端期间，这些输出会进
`~/.zettcode/log/tui.log`，因为直接画上去会把画面弄乱。如果某个服务器看起来毫无反应，先看
这个文件。
:::
