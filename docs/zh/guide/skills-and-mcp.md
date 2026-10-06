# Skills 与 MCP

有两种方式让 ZettCode 学会它本身没有的东西：你自己写的 **skills**，和现成的 **MCP 服务器**。
两者都是“有东西可加载”之前不产生任何开销，因此不会给用不到它们的请求多加一个字。

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

## MCP 服务器

MCP 服务器会发布工具。ZettCode 从 `~/.zettcode/mcp.json`（或 `[mcp] config` 指向的位置）读取，
把每个工具注册成 `<服务器名>__<工具名>`，和自带工具放在一起。

```json
{
  "servers": {
    "docs": {
      "type": "streamable-http",
      "url": "http://127.0.0.1:9000/mcp"
    },
    "browser": {
      "command": "npx",
      "args": ["-y", "some-mcp-server"],
      "env": { "API_KEY": "..." }
    }
  }
}
```

`mcpServers` 是 `servers` 的另一种写法；一个服务器要么是 streamable HTTP 的 `url`（可带
`headers`），要么是 stdio 的 `command`（可带 `args`、`env`、`cwd`）。

没有这个文件就是没有东西可加载，于是一次没配置 MCP 的运行完全不会带上 MCP 相关指令 —— 而不是
放进一条“没有可加载内容”的系统消息。`[mcp] enabled = false` 关掉这个扩展；启动失败的服务器会
被指名报出来，不会让一个挂掉的接入点看起来像请求卡住。

::: tip 话多的服务器弄不坏画面
stdio 服务器会把启动横幅写到 stderr。ZettCode 占用终端期间，这些输出会进
`~/.zettcode/log/tui.log`，因为直接画上去会把画面弄乱。如果某个服务器看起来毫无反应，先看
这个文件。
:::
