# Skills 与 MCP

有两种方式给 ZettCode 它本身没有的东西：**skill** 是你写的指令，**MCP 服务器**是提供工具的程序。两者默认启用，
而且都要先有文件才能加载。

## 什么是 skill

一个 skill 就是一个目录，里面一份 `SKILL.md`：front matter 里写 `name` 和 `description`，正文写指令。

```md
---
name: code-review
description: Review a diff with the team checklist
---

把 diff 读两遍。先看错误处理，再看命名，最后看测试。
发现的问题按严重程度从高到低列出来。
```

在模型判断需要之前，进入模型的只有名字和描述；需要时正文才被读进来。这也是 skills 再多也不会占满上下文的原因。

## 从哪里读 skills 和服务器 {#where-they-live}

| 位置 | 放什么 |
| --- | --- |
| `[skills] roots` | 额外的目录，最先搜索：`roots = ["~/team-skills"]` |
| `<工作区>/.zettcode/skills/`、`<工作区>/.agents/skills/` | 项目自己的，随项目提交 |
| `~/.zettcode/skills/`、`~/.agents/skills/` | 你自己的，在所有项目里生效 |
| `~/.zettcode/`、`~/.agents/`、`<工作区>/.zettcode/`、`<工作区>/.agents/` 下的 `mcp.json` | MCP 服务器 |

同名声明以靠前的位置为准，所以项目里的 skill 在这个项目里胜出。`scope` 决定读哪一边，skills 和服务器都一样：

| `scope` | skills | MCP 服务器 |
| --- | --- | --- |
| `"both"`（默认） | 先项目的，再你的 | 两个文件合并，同名以项目的为准 |
| `"workspace"` | 只有项目的 | 只有 `<工作区>/.zettcode/mcp.json` |
| `"global"` | 只有你的 | `~/.zettcode/mcp.json`，以及 `~/.agents/mcp.json`（`[mcp] config` 指定了文件时不读） |

```toml
[skills]
scope = "global"      # 忽略项目自带的 skills

[mcp]
scope = "global"      # 绝不启动项目自带的服务器
```

::: warning 仓库里的文件默认会被读取
skill 是模型会照着做的指令，MCP 条目是 ZettCode 会执行的命令，所以打开一个带 `.zettcode/mcp.json` 的仓库就会启动它列出的
服务器。像看待一段要运行的脚本那样先看这些文件；对不信任的仓库，把 `scope` 设为 `global`。
:::

## 用 skill

在草稿里输入 `@` 指向一个：

> 用 @code-review 帮我审一下刚才的改动

存下来的消息是 `@code-review` 本身，不是一大段指令。不加 `@` 时，模型看到每个 skill 的名字和描述，任务对得上就去读正文。

菜单里没有你的 skill，就检查目录和 `name` 字段，以及 `[skills] enabled` 是不是 `false`。skill 是指令，不是工具：
它可以要求模型用已有工具，但不会新增。

项目的 skill 放在 `<工作区>/.zettcode/skills/<名字>/SKILL.md`，不需要任何配置。用别人的 skill 前先读一遍。

## MCP 服务器

ZettCode 从 `~/.zettcode/mcp.json`（或 `[mcp] config` 指定的文件）读服务器定义，把每个工具注册成
`<服务器>__<工具>`，和自带工具放在一起。

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

| 参数 | 含义 |
| --- | --- |
| `command` | 本地服务器的可执行程序，进程必须能找到它。 |
| `args`、`env`、`cwd` | 它的参数、环境变量和工作目录。 |
| `url`、`headers` | 远程服务器，配合 `"type": "streamable-http"`。 |

在别处运行的服务器用 URL 指定：

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

`mcpServers` 是 `servers` 的另一种写法。服务器是外部程序，不自带；第一次启动可能要下载包。重启后，按它做的事来点：
“用浏览器工具打开 `http://localhost:3000`，检查是否有控制台错误。”

::: warning MCP 服务器以自己的进程权限运行
它的工具可能产生副作用，shell 的审批提示管不到它们。`env` 或 `headers` 里的密钥不要进版本控制，能用固定版本就别用
`@latest`。
:::

`[mcp] enabled = false` 关掉它。没有文件时什么都不加载。

## 服务器或工具出问题时

| 出了什么问题 | 会发生什么 |
| --- | --- |
| 服务器没起来，或启动很慢 | 这次请求跳过它，对话里有一行说明，模型也会知道这些工具不在。 |
| 工具报错，或服务器中途崩溃 | 这次调用作为失败的工具结果、带着服务器自己的信息回去；一直不返回的调用五分钟超时。 |
| `mcp.json` 里某一项写坏了 | 这一项被忽略并点名，其余服务器照常加载。 |
| 文件根本不是合法 JSON | 本次运行关闭 MCP，并说明原因。修好文件再重启。 |

ZettCode 占用终端时，stdio 服务器的启动横幅会写进 `~/.zettcode/log/tui.log`，服务器看起来没反应时先看这个文件。
