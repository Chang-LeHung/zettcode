---
layout: home

hero:
  name: ZettCode
  text: A coding agent in your terminal
  tagline: Your workspace, your files, your commands. Point it at a project, describe the change, and watch the work happen row by row.
  image:
    src: /logo.svg
    alt: ZettCode
  actions:
    - theme: brand
      text: Get started
      link: /guide/getting-started
    - theme: alt
      text: Keys and mouse
      link: /guide/keys
    - theme: alt
      text: GitHub
      link: https://github.com/Chang-LeHung/zettcode

features:
  - icon: 🖥️
    title: A terminal, not a browser
    details: Mouse selection, scrolling, panels, and copy all work the way a terminal user expects. One workspace, real files, real commands.
  - icon: 🌿
    title: Reads the room
    details: The palette follows your terminal's background, or a theme file, down to the colours used inside code blocks and diffs.
  - icon: 📜
    title: Built for long sessions
    details: Conversations are a tree on disk. Resume any of them, fork by editing, and compact the context window before it fills.
  - icon: 🤝
    title: Asks before it acts
    details: Every shell command is confirmed first, with a one-key way to allow the rest of the run when you trust it.
  - icon: 🧩
    title: Extensible without forking
    details: Project instructions, skills, MCP servers, and Python plugins all plug in through configuration or an entry point.
  - icon: 🪶
    title: Draws only what changed
    details: Frames are diffed cell by cell, so a busy transcript stays smooth on a slow link or a busy machine.
---

<div class="term">
  <div class="term-bar"><span></span><span></span><span></span><em>zettcode &middot; ~/projects/api</em></div>
  <pre class="term-body"><code><span class="t-dim">  ▄███████▄
  █ ██ ██ █</span>   <b>ZettCode</b>
<span class="t-dim">  █   ✦   █</span>   <span class="t-dim">A focused coding agent</span>
<span class="t-dim">  ▀███████▀</span><br/><br/>
<span class="t-dim">  Type a task below, or /help for commands.</span><br/><br/>
<span class="t-acc">›</span> <b>add a limit/offset window to GET /users</b><br/><br/>
  <span class="t-dim">▸</span> <span class="t-text">Read src/api/users.py</span>
  <span class="t-dim">▸</span> <span class="t-text">Edited src/api/users.py (2 edits)</span>
  <span class="t-dim">▸</span> <span class="t-text">Ran pytest tests/test_users.py</span><br/><br/>
  <span class="t-text">GET /users now takes a <span class="t-acc">limit</span> (default 20, max 100) and an</span>
  <span class="t-text"><span class="t-acc">offset</span>, both validated, and the response carries the total so a</span>
  <span class="t-text">client can page without counting. The existing tests still pass.</span><br/><br/>
  <span class="t-dim">Processed for 12s &middot; 09:41</span><br/><br/>
<span class="t-dim">────────────────────────────────────────────────────────────────</span>
<span class="t-bright">▐</span> <span class="t-text">zettcode</span>  <span class="t-dim">~/projects/api</span>                      <span class="t-dim">gpt-4o &middot; high</span>
<span class="t-acc">●</span> <span class="t-text">ready</span>  <span class="t-dim">New session</span>  <span class="t-dim">↑18.4k ↓900 &middot; 71.2% cached &middot; 74 tok/s &middot; ctx 12.3%</span></code></pre>
</div>

## What it is

ZettCode is a terminal client for the model loop in
[`zett-agent`](https://github.com/Chang-LeHung/zett-agent). It sends your
message, streams what comes back, runs the tools the model asks for, and shows
the whole thing as a conversation you can scroll, select, and copy — instead of
a wall of JSON.

There is nothing to set up beyond one config file, and no page to open: the
shell takes the terminal, works, and gives it back when you leave.

## Where to go next

- **[Getting started](/guide/getting-started)** — install it, name a model, and
  send the first task.
- **[The interface](/guide/interface)** — what each row of the screen is telling
  you.
- **[Keys and mouse](/guide/keys)** — the full reference for both.
- **[Commands](/guide/commands)** — every `/command` and `@resource`.
- **[Configuration](/guide/config)** — one file, every key.
