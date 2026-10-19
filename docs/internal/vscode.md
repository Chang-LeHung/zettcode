# The VS Code extension

`clients/vscode` is the editor face of `zettcode-server`, in the same place a terminal is: it drives the HTTP API
through `clients/typescript`, and holds no agent, tools, or session store of its own.

## The shape

| File | What it owns |
| --- | --- |
| `src/extension.ts` | Activation, the status bar, the command palette, and the one `ServerManager`. |
| `src/server.ts` | One `zettcode-server` child: command lookup, free port, a per-window token, health polling, restarts. |
| `src/chat.ts` | The webview provider: runs a prompt, folds its frames into a turn, and answers the webview's actions. |
| `src/html.ts` | The document skeleton, free of the VS Code API so a test can render it. |
| `src/usage.ts` | The panel around the read-only pages (usage, model check, plugins). It only creates the panel and wraps the HTML; it has no script, because the tabs are radio buttons. |
| `src/core/usage-page.ts` | The HTML and CSS of those pages, free of the editor so a test reads them as a document: the terminal's Models, Sessions and Calendar tabs under one totals line. |
| `src/core/usage.ts` | What the usage page works out from the ledger: heat levels (quartiles of the used days), streaks, the week-by-week calendar grid, square-root bar scale, one-decimal shares. |
| `src/core/protocol.ts` | The messages between host and webview, and the state snapshot both agree on. |
| `src/core/state.ts` | The pure reducer: `Turn`, `Block`, `applyEvent`, `finishTurn`, `restoreTurns`. |
| `src/core/format.ts` | Tool-row description, token and time formatting, output clean-up; re-exports the Markdown renderer. |
| `src/core/markdown.ts` | The one Markdown renderer (`marked`): GitHub tables, task lists, bold that works beside CJK text, file links, no raw HTML. |
| `src/core/math.ts` | TeX in an answer, typeset by KaTeX as MathML (the editor's browser draws it, so no font or style sheet ships); cached, and a formula it cannot read comes back as its own source. |
| `src/core/escape.ts` | `escapeHtml` alone, so the editor-host half imports no Markdown, KaTeX or highlighter (that is what keeps `dist/extension.js` small). |
| `src/core/highlight.ts` | Syntax highlighting (`highlight.js` core plus about 70 registered grammars and the names people give them), cached. |
| `src/core/levels.ts` | What a reasoning effort and a shell permission look like: rank, tone, icon, and which two levels move. |
| `src/core/diff.ts`, `src/core/ledger.ts` | Line diffs and the in-memory per-request change ledger the "files changed" card and the editor diff read. |
| `src/core/paths.ts` | `path:line:column`, `path#L12`, and whether a token is a path at all. |
| `src/core/chart.ts` | Donut geometry and SVG: exact shares, minimum visual slices, gaps, and the tone classes the context card uses. |
| `src/core/permission.ts` | The permission level to approval-policy mapping; one table, tested without an editor. |
| `src/webview/main.ts`, `App.vue` | The webview program: a Vue 3 application mounted on an empty document. |
| `src/webview/store.ts` | The one reactive store: the host's state, the transcript, queue, toasts, which panel is open, and the compaction row (drawn the moment `/compact` goes out, ended by the host's next notice). |
| `src/webview/commands.ts` | The slash commands: which take arguments (`/btw`, `/rename`), how Tab completes and Enter runs, and how a line is parsed. |
| `src/webview/context.ts` | The context card's rows: sources in the terminal's order, `pending` rows, shares scaled to the provider's total. |
| `src/webview/components/*.vue` | One component per part (turn, tool step, output block, composer, menus, context card, compaction slider, drawer, logo, splash, and `MessageRail.vue`, the bars along the left edge that jump between your messages). The reader's message sits on the right in `TurnView.vue`, with its time, copy and edit shown on hover. Templates are compiled at build time by `scripts/vue-plugin.mjs`; CSS is extracted to `dist/webview.css`. |
| `media/base.css` | Design tokens (neutral surface, a mint-to-gold brand gradient taken from the mascot, a tone per meaning), syntax colours and the Markdown styles. |
| `media/brand/*.svg` | The mascot artwork in its variants (cloud, moon, dark, white, green, transparent); source files only, none ships. |
| `media/logo.svg` | The logo: the transparent moon variant cropped to a square around the mascot (only the gradients it draws), so it fills an icon slot the way other extensions' marks do. The webview inlines it, and the editor-title button, the usage pages and the READMEs load it. |
| `media/icon.png` | The extension icon: the same mascot on a transparent background, cropped to its solid part and rendered at 256px. |
| `media/sidebar.svg` | A single-colour terminal glyph; the activity bar paints icons as masks, so a coloured logo cannot go there. |

The extension bundles `clients/typescript/src` directly (`esbuild` follows the `.js` specifiers to `.ts`), so there is
one client and one set of wire types. The webview is a second bundle; it imports `core/format`, `core/paths`, `core/chart` and the
protocol types, which is why a tool row is described the same way in both halves.

## The rules its tests pin

The main `docs/internal/invariants.md` table is read by a Python test that only looks for Python test functions, so
this client's load-bearing rules live here and are named by the `npm test` case that fails when they break.

| # | Rule (what breaks) | Test |
| --- | --- | --- |
| V1 | The extension speaks HTTP only, through `clients/typescript`: no source imports the Python packages, the SDK, or `zettcode_server`, and no second wire parser appears beside the client. | `layers.test.ts` — "the extension speaks HTTP through the TypeScript client" |
| V2 | The webview never holds the token or calls the server: only the extension-host modules import `vscode` and the client, and the reducer and webview stay free of both. Every action is a posted message. | `layers.test.ts` — "only the extension host imports vscode and the HTTP client" |
| V3 | A turn's consecutive tool calls are one connected rail, not detached rows; an approval or question belongs to that rail, and its answer is posted for the call id it names. | `webview.test.ts` — "the transcript renders a turn, a connected tool rail and a file link", "an approval is answered from the card" |
| V4 | A path in an answer or a tool row is a link with the place it named; a directory is revealed, a file opens at its line and column. Parsing is one function, shared by both halves. | `paths.test.ts`, `webview.test.ts` — "the transcript renders a turn, a connected tool rail and a file link" |
| V5 | Shell permission maps to one approval policy and one server setting: `deny` refuses, `ask`/`safe` ask (safe runs read-only commands server-side), and `auto` runs everything. | `permission.test.ts` — "each permission level maps to one approval policy" |
| V6 | A composition donut keeps the exact one-decimal percentages in its legend while tiny slices are enlarged only for drawing, never divides by zero, and emits valid dash patterns; an unknown tone falls back to muted. | `chart.test.ts` — "a donut keeps exact percentages and draws a full ring", "a tiny slice is enlarged for the drawing and the exact value stays in the legend", "no values is an empty ring, not a division by zero", "the SVG carries a slice per source and escapes the label" |
| V7 | An answer's Markdown never runs HTML, bold works beside Chinese and Japanese punctuation and around code, fenced code is coloured for the mainstream languages by any name, and a domain such as `openrouter.ai/api/v1` is never offered as a file to open. | `markdown.test.ts` — "bold works next to Chinese text and punctuation, where CommonMark gives up", "the mainstream languages are coloured, whatever name the fence uses", "a domain with a path is an address, not a file to open", "raw HTML, scripts and unsafe links never run" |
| V8 | Until the first load finishes the view shows only the mark, so it never claims "no model" about a server it has not asked yet; a server that failed to start is reported instead of waited for. | `webview.test.ts` — "while the first load runs only the mark shows, never a guess about models", "a server that failed to start is reported instead of waited for" |
| V9 | A message typed during a run is a follow-up: it waits, goes out when the run ends well, stays put when the run was stopped, and can be steered in on request. | `webview.test.ts` — "a message sent during a run waits as a follow-up, and can be steered in", "a follow-up goes out by itself when the run ends well, and waits when it was stopped" |
| V10 | The compaction point moves in steps of 5%, applies only on Enter or Apply, can be undone with Esc, and is locked while a run is in progress. | `webview.test.ts` — "the compaction point is a rail: keys move it by 5%, Enter applies it, Esc undoes it", "the Apply button sends the new point, and a run in progress locks the rail" |
| V11 | `/compact` shows a running row at once and ends it with the host's one reply: only that the conversation was compacted (never the summary), that there was nothing to compact, or why it failed; while a run is busy it is refused with a toast and leaves no row. | `turns.test.ts` — "compacting shows a row at once, then only that it was compacted, never the summary", "compacting while a run is busy is refused with the reason, and no row is left", "a compaction that finds nothing to do says so", "a compaction that fails ends the row with the reason" |
| V12 | The reader's message sits on the right with its time, a copy button and an edit button; a turn read back from the store shows no time rather than a wrong one. | `turns.test.ts` — "a message sits on the right with its time, a copy button and an edit button" |
| V13 | The usage page is the terminal's three tabs under one totals line, switchable without a script; shades are the quartiles of the used days, a streak survives a morning not yet used, and a month name never lands on the next. | `usage.test.ts` — "the usage page has the terminal's three tabs under one line that totals the workspace", `usage-core.test.ts` — "shades are the quartiles of the days that were used, and an unused day has none", "a streak survives a morning that has not been used yet", "a month name that the next month would be drawn over is left out" |
| V14 | A formula (`$x$`, `\(x\)`, `$$ … $$`, `\[ … \]`) is typeset, but a price, a shell variable, a `$` in code or an escaped `\$` never is; a formula KaTeX cannot read shows its source and leaves the answer around it; `\href` and `\includegraphics` never become a link or a picture. | `markdown.test.ts` — "formulas are typeset in all four spellings, inline or on their own line", "prices, shell variables and code are never read as formulas", "a formula KaTeX cannot read shows its source and leaves the rest of the answer alone" |
| V15 | The editor-host half carries no Markdown renderer, typesetter or highlighter: no host file reaches `core/markdown.ts`, `core/math.ts` or `core/highlight.ts` through its imports, so KaTeX and highlight.js stay out of `dist/extension.js`. | `layers.test.ts` — "the editor-host half reaches no Markdown renderer, typesetter or highlighter" |
| V16 | The box's own text is transparent and a layer behind it draws the letters, so that layer follows what the box holds right now, not the draft: while an input method is composing (pinyin, kana) `v-model` leaves the draft alone until a word is chosen, and a layer that read the draft would show nothing of the letters being typed. | `composition.test.ts` — "letters typed through an input method are drawn while they are still being composed" |
| V17 | A change of model, reasoning effort or shell permission is a line across the transcript with its words in the middle, between the two requests it separates, as the terminal draws it; it is not a request (no bubble, no answer, no receipt), and it never hides how the last request ended, so a follow-up still waits after a stopped run. | `announce.test.ts` — "a change of model, effort or permission is a line across the view with its words in the middle", "a line that announces a change is not a request: folding all requests leaves it, and it hides nothing", "a follow-up still waits after a stopped run when a change was announced after it" |
| V18 | Work in progress is told by its words, not by a spinner: the "Processing…" line and a running compaction shimmer, and when the run waits for the reader the shimmer stops and a pulsing dot says so. | `announce.test.ts` — "while a request runs its words shimmer and nothing spins", "when it waits for you the label stops shimmering and a pulsing dot says so"; `turns.test.ts` — "compacting shows a row at once, then only that it was compacted, never the summary" |
| V19 | The "files changed" card compares a file with what it really held before the request touched it, not with a remembered copy that went stale: a file a shell command removed or the reader changed since it was last seen is read afresh unless the write or edit has already landed (the file then holds exactly what the write put there, or the edit can be undone on it). A file the request creates is all additions. Files a shell command changes are not tracked. | `ledger.test.ts` — "a file made new by a write is all additions, even if it was remembered as something else", "a write that replaces a file changed behind the ledger's back compares with what was really there", "a write that already landed still compares with the remembered text", "an edit on a file changed behind the ledger's back compares with what was really there", "an edit that landed on a file changed behind the ledger's back is rebuilt from its own arguments" |
| V20 | A usage bar starts where its track starts: no page-wide rule styles a bare `.in` or `.out` (the summary line once did, and shoved every bar's fill 8px right), and the dimmed part of a bar is the cached share of the input or the reasoning share of the output. The calendar draws a year of weeks. | `usage-bars.test.ts` — "no rule styles a bare .in or .out: those names are the bars' own, and a page-wide rule shoved them sideways", "a model's input bar dims the part the cache served, and its output bar the part spent thinking"; `usage.test.ts` — "the calendar tab draws a week in each column and says the streaks" |
| V21 | The extension page is written for the person using the extension: no build commands, file names or architecture in `README.md` (they live here), no relative address anywhere (the page is rendered by the marketplace, which cannot load a file beside the README), and its picture is a PNG at an absolute address in this repository, never a `data:` URI (the marketplace strips those). | `readme.test.ts` — "every address in the README is absolute, and its picture is a PNG the marketplace can fetch", "the README introduces the extension to the person using it, not to the person building it" |
| V22 | The agent's news (an MCP server starting, ready, down, or an entry ignored) is drawn in the transcript through the same Markdown as an answer, names as code and raw HTML as text; progress is quiet, a warning has an icon, a colour and an `alert` role, and while a server starts the status line says what is happening, without quotes and never with a warning. | `notices.test.ts` — "an MCP server starting and failing is shown in the transcript, as Markdown, a warning standing out", "names in the agent's news become code, but an apostrophe does not", "raw HTML in a notice is shown as text, never run", "while a server starts the status line says what is happening, and a warning is not mistaken for it" |
| V23 | Hovering a day in the usage calendar opens a box at once (not the browser's delayed `title`) with that day's weekday and date, tokens, input and output, requests and cached share, or "Nothing spent"; it opens away from the nearest edge so it is never cut off, belongs to days up to today only, and needs no script. | `usage-calendar.test.ts` — "hovering a day shows that day's date, tokens, input and output, requests and cached share", "every day up to today has a box, a day after today has none, and the slow native title is gone", "the box opens away from the nearest edge, so no day's figures are cut off", "the box is drawn by CSS from the day's own text, with no script" |
| V24 | A conversation with two or more messages has a rail of small bars on the left, one for each message the reader sent (not a side question, a command's row or an announcement). The bars swell toward the pointer like a dock and the nearest shows its message; a click scrolls to that message and makes it flash once; the bar for the message the reader is at is marked and follows the scrolling; the arrow keys, Home and End step through them. | `rail.test.ts` — "a tick for each message you sent, and none for what you did not", "with a single message there is nothing to jump between, so there is no rail", "ticks swell toward the pointer like a dock, and the nearest shows its message", "clicking a tick scrolls to that message and makes it flash once", "the tick for the message you are at is marked, and follows the scrolling", "the arrow keys step between messages, and Home and End go to the ends" |
| V25 | A finished request ends in a receipt that says `Processed` (never `Done`, and in no green; only a stopped or failed request has a colour), then its time and figures, as plain text that cannot be selected or pressed. The usage pages write input and output as ↑ and ↓, as the receipt does. | `steer-paging.test.ts` — "the receipt says Processed in plain text, with its time and figures after it, and nothing to press", "a stopped request keeps its own word and colour"; `usage-calendar.test.ts` — "hovering a day shows that day's date, tokens, input and output, requests and cached share" |
| V26 | A steer is drawn in the running request the moment it is sent, with a hint until the run reports it; the report settles that block instead of adding a second, a steer that reached no run is taken back, and identical steers settle one at a time. | `steer-paging.test.ts` — "a steer shows at once and the run's report of it settles that block instead of adding another", "two identical steers are two blocks, settled one at a time", "a steer that never reached a run is taken back, and a run that ends leaves none pending", "the view draws a pending steer with what it will do, and drops the hint once it is taken up" |
| V27 | A compaction can be opened to read its summary, live and after a reload; a reloaded compacted session shows the compaction row, not the summary as a message the person typed. | `steer-paging.test.ts` — "a finished compaction can be opened to read its summary", "a reloaded compacted session starts with the compaction row, not a message the person typed" |
| V28 | A reloaded conversation shows only its latest page of requests; "show earlier" fetches the page before it, which goes in front without repeating a request or moving what the reader was looking at. | `steer-paging.test.ts` — "a page starts so that it holds the latest requests and leaves no orphan rows behind", "a long reloaded conversation shows its latest page and loads older ones in front on request", "an older page that overlaps what is on show does not repeat a request" |
| V29 | Every wait is told by one `Shimmer` (a band of light about eight characters wide crossing the words for a second, then resting a second, as in the terminal's waiting row), with no spinner and no trailing dots: the status line, a live thought, a running compaction and the newest progress line. | `steer-paging.test.ts` — "waiting words lose their trailing dots, and the newest progress line of a running request shimmers"; `announce.test.ts` — "while a request runs its words shimmer and nothing spins"; `turns.test.ts` — "compacting shows a row at once, then only that it was compacted, never the summary" |
| V30 | Code is coloured by a palette of our own, not the editor's symbol-icon colours (most themes leave those plain, so keywords looked like text); a fence still streaming is coloured already and a half-typed closing fence is not code; a fence with no language is coloured when the highlighter is sure. | `steer-paging.test.ts` — "keywords, strings and numbers are coloured by a palette of our own", "a code block that has not closed yet is already coloured, and a half-typed closing fence is not code", "a block with no language is coloured when the highlighter is sure, and left plain when it is not" |
| V31 | The conversation and the message box fill a wider panel up to one shared width, with a margin that grows with the panel but stays small; an edit's row shows the lines it added and removed. | `steer-paging.test.ts` — "the conversation and the message box grow with the panel and keep a margin at both sides", "an edit row shows the lines it added and removed, and a file written whole the lines it holds" |
| V32 | `Ctrl+F` (`Cmd+F` on a Mac) opens a search over the conversation on show, with the cursor in it and a short selection as the query. It counts the matches ignoring case, never in buttons or scripts; `Enter`/`Shift+Enter` (or `F3`) step through them and wrap round, `Escape` closes it and returns to the message box, and the matches are found again as the conversation grows. | `find.test.ts` — "a query is found wherever it occurs…", "stepping wraps round at both ends…", "Ctrl+F opens a search that counts the matches, steps through them and closes with Escape", "Cmd+F does the same on a Mac…", "an open search follows the conversation as it grows" |
| V33 | The shell permission the reader chooses is remembered by the extension, not left to the server (which forgets it on every restart): each session gets back the level it was last set to, a session with none starts from the last level chosen in the workspace, a level the server does not offer or a damaged stored value is ignored, and only the newest 200 sessions are kept. | `remember.test.ts` — "a session gets back the permission it was last set to, and a new one the last choice made here", "a level the server does not offer is not asked for", "what was stored is read back through a filter…", "only the newest sessions are kept…", "the chat view puts the remembered permission back whenever a session is read, and saves each choice" |

## Building, trying and packaging it

```bash
make vscode           # install, type-check, test and build the extension
make vscode-package   # also write clients/vscode/zettcode-0.1.1.vsix
code --install-extension clients/vscode/zettcode-0.1.1.vsix --force
```

Or open `clients/vscode` in VS Code and press **F5** to run it in an Extension Development Host. From
`clients/vscode`:

```bash
npm run check    # vue-tsc, no emit
npm test         # reducer, Markdown, paths, ledger, usage pages, and the webview in jsdom
npm run build    # dist/extension.js and dist/webview.js
npm run watch    # rebuild both bundles on change (reload the extension host)
npm run package  # build, then write the .vsix through scripts/package.mjs
```

`scripts/package.mjs` packs the README as it is: every address in it is absolute, and the picture is the PNG on
`raw.githubusercontent.com`, because the extension page is rendered by the marketplace, which fetches pictures from
public addresses and strips a `data:` URI (the 0.1.0 page showed a broken image for exactly that reason). `vsce` is told
`--no-rewrite-relative-links`, so it leaves the addresses alone.

The webview test renders the real document and bundle, then drives the buttons: a turn with a tool rail, an approval, a
question, a prompt, the model sheet, the session drawer and steering.

How the halves fit together: `chat.ts` owns the webview and the conversation. It starts a run with the TypeScript client,
folds each SSE frame into a `Turn` (the pure reducer in `src/core/state.ts`), and posts the changed turn to the webview at
most every 60 ms. The webview never talks to the server: it posts a small message (`prompt`, `approve`, `open`,
`set-model`, ...) and the host does the HTTP call and posts state back, which keeps the token in the host.

## Server lifecycle

- One child per window, in the first workspace folder. A configured external URL is used instead of spawning.
- The command is a path when it contains a separator; a bare name is looked up in the workspace's `.venv/bin`
  (or `.venv/Scripts`), then on `PATH`. This is what makes `uv sync` in a checkout work without installing globally.
- The configured port is tried; if it is in use, a free loopback port is chosen. A token is generated per window and
  passed in `ZETTCODE_SERVER_TOKEN`, so it is not in the process's argument list.
- The server is polled at `/health` until ready. An unexpected exit is reported and retried three times with a
  growing delay; an explicit restart increments the generation so an old child's exit cannot mark the new one failed.
- `--permission` seeds the server. The extension changes it with `PATCH /settings`, and each prompt maps the current
  level to its approval policy.

## State flow

A run is consumed once: `for await (const frame of run)`. Each `event` frame goes through `applyEvent`, each `result`
through `finishTurn`; the turn is posted whole, throttled to one message per 60 ms, and immediately for a tool
boundary, approval, question, notice or the end. The webview keeps only view state (open tool rows, open reasoning,
composer text, attachments); the truth is the host's `turns` array, restored from `/sessions/current/history` and
paired tool calls with their `tool` messages.

Streaming stops when the stream ends, the reader cancels (`POST /runs/cancel`), or the connection closes. The host
does not use the client's `onApproval`/`onQuestion` handlers: a request is drawn as a card and answered by a separate
POST, which is what lets one card be answered after a window reload.
