# 快速开始

ZettCode 是跑在终端里的编码智能体。它在一个目录里工作，把每次工具调用显示成一行，执行 shell 命令前先问你。

## 需要什么

- Python 3.10+，macOS、Linux 或 Windows 都可以（Windows 请用 Windows Terminal）。
- 一个 OpenAI 兼容接口，或 Anthropic 的 Messages API，以及对应的 token。

## 安装

::: code-group

```bash [uv]
uv tool install "zettcode[all]"
```

```bash [pip]
pip install "zettcode[all]"
```

:::

引号要保留：`fish` 和 `zsh` 会把没加引号的 `[all]` 当作通配符。单独的 `zettcode` 是终端、网页网关、服务器和
SDK；`[all]` 另外带来四个插件：`/monitor`、`/recap`、各厂商模型，以及作为群成员的 Codex 和 Claude Code。

## 连接模型 {#先配一个模型}

运行 `zettcode`，在窗口里加一个模型：

```text
/config add --model deepseek-v4-pro --token sk-... --url https://api.deepseek.com --context 1m --name "DeepSeek Pro"
```

这会把一条 `[[models]]` 写进 `~/.zettcode/config.toml`，并把它设为当前模型。模型 id 和 API 根地址用你供应商的，
token 是密钥。

也可以直接写文件：

```toml
[[models]]
model = "deepseek-v4-pro"
display_model = "DeepSeek Pro"
token = "sk-..."
base_url = "https://api.deepseek.com"
context_window = 1000000
```

所有键、多模型配置和环境变量见[配置参考](/zh/guide/config#models)。

## 发出任务

在你要工作的目录里启动：

```bash
cd ~/projects/api
zettcode
```

输入任务，按 **Enter**：

> 给 GET /users 加上 limit/offset 分页，并补上测试

说清楚范围和怎么验证，比“优化一下项目”好审阅。第一次看一个陌生仓库，可以先只读：

> 说明这个项目的入口在哪里，以及如何运行测试。先不要修改文件。

模型要执行 shell 命令时，面板会先问你：`y` 执行一次，`p` 记住这条，`s` 不再问只读命令，`a` 不再问，`Esc` 拒绝。
文件编辑不会问，所以接受改动前先看 diff。

输入框为空时按 **Ctrl-D** 退出，终端会打印恢复当前会话的命令。

## 下一步

- [它能做什么](/zh/guide/capabilities)：JIT harness、`/code-review`、后台 agent、群和网关。
- [界面](/zh/guide/interface)：屏幕上每一行是什么意思。
- [命令](/zh/guide/commands)：所有斜杠命令，以及 `zettcode` 命令行。
