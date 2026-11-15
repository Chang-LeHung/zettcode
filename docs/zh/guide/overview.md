# 找到你的下一步

ZettCode 是一个跑在终端里的编码智能体，操作一个目录里的文件，运行 shell 命令前先问你。按你眼下要做的事选一条路。

## 第一次使用

- **[快速开始](/zh/guide/getting-started)。** 安装、连接模型、跑第一个任务。需要 Python 3.10+，以及一个
  OpenAI 兼容或 Anthropic 接口的 token。
- **[看它能做什么](/zh/guide/capabilities)。** 超出“一个终端一个会话”的八件事，每件都附一条能启动它的命令。
- **[认识界面](/zh/guide/interface)与[快捷键](/zh/guide/keys)。** 屏幕上每一行是什么意思；Enter 发送，
  Ctrl-C 停止请求，输入框为空且没有任务时 Ctrl-D 退出。

## 日常使用

- **[命令参考](/zh/guide/commands)。** 每个斜杠命令和每个 `zettcode` 选项，都在表格里。
- **[会话管理](/zh/guide/sessions)与[上下文窗口](/zh/guide/context)。** 继续昨天的对话、导出成 HTML，
  看清模型的窗口还剩多少。
- **[JIT harness](/zh/guide/harness)。** 模型为当前任务写一个小工具，加载后直接调用。

智能体工作时继续输入，会问你这条消息是 **steer（引导）** 正在运行的请求，还是作为 **follow up（后续）** 单独发出。
只想顺口问一句、又不想这个答案进入后续请求的上下文，就用 `/btw <问题>`。[界面说明](/zh/guide/interface)讲清了这三种用法。

## 和多个智能体一起

- **[代码评审](/zh/guide/code-review)。** 另一个智能体读你未提交的改动，说出它会改什么。
- **[后台 agent](/zh/guide/daemons)。** 没人坐在键盘前的会话，关掉终端后仍在运行。
- **[会话之间互发消息](/zh/guide/messaging)、[网页网关](/zh/guide/gateway)、[桌面端与手机端](/zh/guide/app)、
  [Codex 与 Claude Code](/zh/guide/code-agents)。** 会话之间互相发消息、加入群，也能在浏览器里看着它们工作。

## 按你的方式配置

[配置参考](/zh/guide/config)讲模型、权限和主题；[项目指令](/zh/guide/instructions)把你的约定写进 `AGENTS.md`；
[Skills 与 MCP](/zh/guide/skills-and-mcp)和[插件](/zh/guide/plugins)增加命令与工具。[SDK](/zh/sdk/)让你在
Python 里驱动同一个智能体。

卡住了？先看[常见问题](/zh/guide/faq)。能复现的 bug 请到
[GitHub 提交 issue](https://github.com/Chang-LeHung/zettcode/issues)，附上操作系统、终端、版本和复现步骤。
