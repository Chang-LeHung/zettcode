---
layout: home

hero:
  name: ZettCode
  text: 在终端里干活的编码智能体
  tagline: 用你的工作区、你的文件、你的命令。指向一个项目，说清楚要改什么，然后看着它一行行做出来。
  image:
    src: /logo.svg
    alt: ZettCode
  actions:
    - theme: brand
      text: 快速开始
      link: /zh/guide/getting-started
    - theme: alt
      text: 快捷键与鼠标
      link: /zh/guide/keys
    - theme: alt
      text: GitHub
      link: https://github.com/Chang-LeHung/zettcode

features:
  - icon: 🖥️
    title: 是终端程序，不是网页
    details: 鼠标选中、滚动、弹窗、复制都按终端用户的习惯来；一个工作区，真实的文件和真实的命令。
  - icon: 🌿
    title: 跟着你的终端配色
    details: 自动识别终端背景是深色还是浅色，也可以用自己的主题文件，连代码块和 diff 里的颜色都能定义。
  - icon: 📜
    title: 为长会话设计
    details: 对话在磁盘上是一棵可回溯的树：随时恢复、随时压缩上下文，会话再长也不会失控。
  - icon: 🤝
    title: 动手之前先问你
    details: 每条 shell 命令都要确认；信任之后一个键就能放行这一轮剩下的命令。
  - icon: 🧩
    title: 不用改代码就能扩展
    details: 项目指令、Skills、MCP 服务器、Python 插件，都能通过配置或 entry point 接进来。
  - icon: 🪶
    title: 只重画变化的部分
    details: 每一帧按单元格做差异渲染，机器再忙、会话再长也保持流畅。
---

<div class="term">
  <div class="term-bar"><span></span><span></span><span></span><em>zettcode &middot; ~/projects/api</em></div>
  <pre class="term-body"><code><span class="t-dim">  ▄███████▄
  █ ██ ██ █</span>   <b>ZettCode</b>
<span class="t-dim">  █   ✦   █</span>   <span class="t-dim">专注的终端编码智能体</span>
<span class="t-dim">  ▀███████▀</span><br/><br/>
<span class="t-dim">  在下面描述任务，或输入 /help 查看命令。</span><br/><br/>
<span class="t-acc">›</span> <b>给 GET /users 加上 limit/offset 分页</b><br/><br/>
  <span class="t-dim">▸</span> <span class="t-text">Read src/api/users.py</span>
  <span class="t-dim">▸</span> <span class="t-text">Edited src/api/users.py (2 edits)</span>
  <span class="t-dim">▸</span> <span class="t-text">Ran pytest tests/test_users.py</span><br/><br/>
  <span class="t-text">GET /users 现在接受 <span class="t-acc">limit</span>（默认 20，上限 100）和</span>
  <span class="t-text"><span class="t-acc">offset</span>，两者都会校验；响应里带上总数，客户端不必</span>
  <span class="t-text">自己数就能翻页。现有测试全部通过。</span><br/><br/>
  <span class="t-dim">Processed for 12s &middot; 09:41</span><br/><br/>
<span class="t-dim">────────────────────────────────────────────────────────────────</span>
<span class="t-bright">▐</span> <span class="t-text">zettcode</span>  <span class="t-dim">~/projects/api</span>                      <span class="t-dim">gpt-4o &middot; high</span>
<span class="t-acc">●</span> <span class="t-text">ready</span>  <span class="t-dim">New session</span>  <span class="t-dim">↑18.4k ↓900 &middot; 71.2% cached &middot; 74 tok/s &middot; ctx 12.3%</span></code></pre>
</div>

## 它是什么

ZettCode 是 [`zett-agent`](https://github.com/Chang-LeHung/zett-agent) 模型循环的终端客户端：
它把你的消息发出去，把回来的内容流式画出来，执行模型要求的工具，并把整个过程变成一段可以
滚动、选中、复制的对话 —— 而不是一屏 JSON。

除了一份配置文件，没有别的东西要装，也没有网页要打开：它接管终端，干完活，退出时把终端还给你。

## 接下来看哪里

- **[快速开始](/zh/guide/getting-started)** —— 装好、配一个模型、发出第一个任务。
- **[界面](/zh/guide/interface)** —— 屏幕上每一行在告诉你什么。
- **[快捷键与鼠标](/zh/guide/keys)** —— 完整对照表。
- **[命令](/zh/guide/commands)** —— 所有 `/命令` 与 `@资源`。
- **[配置文件](/zh/guide/config)** —— 一个文件，所有键都在这里。
