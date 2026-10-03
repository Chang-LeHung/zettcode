# TUI Framework

`src/zettcode/tui` is a terminal UI toolkit that knows nothing about
the coding agent. ZettCode is its first consumer, not its definition. This
document is the contract and the roadmap for that framework.

## Boundary

Three rules define the framework:

1. No module under `tui` may import `zett_agent`.
2. The application imports only the public surface; the framework never imports
   the application.
3. The framework ships primitives, the application owns semantics. A `Dialog`,
   a `List`, or a `DiffView` is a framework widget; the decision to approve one
   shell command is application policy.

The test is simple: if a capability stops making sense once the coding agent is
removed, it does not belong here.

## Reading order

The change looks enormous because the previous implementation was deleted
outright (+305 lines in tracked files, -2814). Treat this as a new codebase
rather than a diff, and read it bottom-up in three passes.

**Pass 1 — the closed loop (five files, ~800 lines).** `core/geometry.py` (the
data), `core/events.py` (the input model), `core/widget.py` (the contract),
`core/app.py` (routing, focus, screens, painting), `runner.py` (the terminal
loop). Everything else is built on these.

**Pass 2 — the application (~880 lines).** `app/agent/transcript.py` owns the
conversation model and the render cache behind each entry,
`app/agent/projection.py` maps agent events onto it, and `app/ui/app.py` owns
the keymap, the slash commands, and the approval panel. `app/ui/transcript.py`
is the scrollable, virtualized view over the model.

**Pass 3 — by need.** `render/` for text and colour, `input/` and `terminal.py`
for the TTY, `layout/` for boxes and scrolling, `widgets/` for the component
library. Read only the widget you care about; `textarea.py` is the largest at
434 lines because it implements Readline editing.

The tests are the executable specification. Reach for `tests/test_app.py` for
routing precedence, `test_layout.py` for the solver and selection,
`test_zettcode_app.py` for end-to-end application behaviour, `test_performance.py`
for the caching claims, and `test_golden.py` for what a frame should look like.

## Layers

Dependencies point downward only. `render` is a leaf utility: it depends on
nothing but `wcwidth`, so `terminal` and `core` both build on it.

```
testing      headless driver and snapshot assertions (shared with consumers)
widgets      List / Dialog / TextArea / Table / Diff / Markdown / Toast ...
core         TuiApp loop, screen stack, focus tree, event routing, keymap, scheduler, theme
layout       Rect, constraints (fixed/flex/min/max), Box/Overlay, scrolling
render       Style/Span/Canvas, differential renderer, width and wrapping
input        byte-stream decoding, key tables, paste/mouse/resize/focus events
terminal     raw mode, alternate screen, size, capability detection
```

Layout as of M6:

```
src/zettcode/
  cli.py, config.py  the outermost layer: entry point and validated settings
  app/               the ZettCode application, built on the framework
    agent/           transcript.py (the conversation model and its render
                     cache), projection.py (agent events into that model),
                     runtime.py (AgentClient and composition), title.py (the
                     one-shot session naming call), storage/ (the workspace
                     layout, the JSONL conversation tree, metadata.jsonl, and
                     the persistence plugin)
    ui/              app.py (shell, keymap, commands), transcript.py (the
                     virtualized view over the model)
  tui/               the reusable, agent-agnostic framework
```

The arrows only point one way: `ui` reads `agent`, `agent` builds on `tui`, and
nothing under `tui` knows the application exists. `app/__init__.py` is the
facade over both halves, so callers keep writing `from zettcode.app import
ZettCodeApp`.

Inside the framework:

```
tui/
  capabilities.py   environment-derived terminal capabilities
  terminal.py       raw mode, alternate screen, size
  runner.py         terminal-backed async loop over a TuiApp
  input/            events.py, keys.py, decoder.py, reader.py, bridge.py
  render/           style.py, text.py, color.py, canvas.py, renderer.py
  core/             geometry.py, events.py, host.py, widget.py, theme.py,
                    focus.py, screen.py, keymap.py, scheduler.py, app.py
  layout/           solver.py, box.py, spacing.py, overlay.py, scroll.py
  widgets/          list.py, textarea.py, dialog.py, table.py, completion.py,
                    status.py, progress.py, toast.py, collapsible.py,
                    diff.py, markdown.py, text.py, tasks.py
  testing/          harness.py
```

The framework is complete for the shipping application and holds no reference to
the agent or to `zettcode.app`. The old `components.py`, `application.py`, and
`tui.py` are gone: `src/zettcode/app/` is the only implementation of the
application now.

## Core contracts

`core/geometry.py` owns `Point`, `Size`, `Rect`, `EdgeInsets`, and
`Constraints`. These are the only geometry types in the framework; the legacy
`components.Rect` is a re-export of `core.geometry.Rect`.

`core/events.py` owns the input model: `EventKind`, `MouseAction`, the `Event`
base with modifier flags, and the concrete `KeyEvent`, `TextEvent`,
`PasteEvent`, `MouseEvent`, `ResizeEvent`, and `FocusEvent`. `AnyEvent` is the
union every widget receives.

`core/host.py` defines `Host`, the services a running tree exposes to its
widgets: `focus`, `focused_widget`, `invalidate`, `request_layout`, `copy`,
`refresh`, and `exit`. Widgets never touch the terminal directly, which is what
makes the tree drivable without a TTY.

`render/text.py` is the single source of truth for text measurement:
`cell_glyph`, `character_width`, `display_width`, `slice_columns`, `truncate`,
`wrap_columns`, `expand_tabs`, and `expand_span_tabs`. `render/color.py` owns
`ColorDepth` and encodes one `Style` as SGR for truecolor, 256-color, 16-color,
or monochrome output.

`render/renderer.py` writes only the ranges that changed, and it does so with a
closed vocabulary: Erase in Display (`ED`), Cursor Position (`CUP`), Select
Graphic Rendition (`SGR`), and the cursor show/hide pair (`DECTCEM`). Every
sequence in the codebase is commented where it is written, and the terminal
layer's mode switches (`terminal.py`) and the input decoder's key tables are
documented the same way, because a bare `ESC[?...h` is unreadable on its own.

`capabilities.py` derives a `TerminalCapabilities` record from the environment.
Detection only consults variables such as `TERM`, `COLORTERM`, `NO_COLOR`, and
the locale, and every default errs toward the weaker terminal. The mouse and
bracketed-paste flags decide which modes `terminal.py` enables and restores, so
a caller can describe a plainer terminal and have the layer speak only what it
understands; `unicode` is advisory until widgets grow ASCII glyph fallbacks.

`core/widget.py` defines `Widget`:

| Member | Role |
|---|---|
| `children` | Paint order for the subtree |
| `mount` / `unmount` | Attach and detach, running lifecycle hooks once |
| `measure(constraints)` | Preferred size within a range |
| `layout(rect)` | Assign the final rectangle, firing `on_resize` on change |
| `render(canvas)` | Paint into the shared cell canvas |
| `handle(event, host)` | Consume input, returning whether it was handled |
| `cursor()` | Requested terminal cursor position |
| `on_mount` / `on_unmount` / `on_resize` / `on_focus` / `on_blur` | Lifecycle hooks |
| `invalidate` / `request_layout` / `clear_dirty` | Dirty tracking |
| `focusable` | Whether Tab traversal may land here |
| `capture_event` / `bubble_event` | Optional hooks in the routing phases |
| `app` / `theme` | Back-reference to the running app and its theme |

## Runtime

`core/app.py` owns one tree: screens, focus, keymap, scheduler, theme, layout,
and painting. `TuiApp` is the only `Host`, so widgets reach the outside world
only through it. It never touches a terminal, which is what lets the same tree
run under a TTY or headlessly.

`core/host.py` is the narrow waist between the two. `handle(event, host)` hands
every widget the same seven capabilities — focus, focused_widget, invalidate,
request_layout, copy, refresh, exit — so a widget never imports `TuiApp`, and the
keymap's commands go through the same door. `Host` is an abstract base class
rather than a protocol, so an implementation subclasses it and answers every
method; a class that merely looks compatible does not count.

The interface covers input-time capabilities only. A widget that needs the clock
or the screen stack during a lifecycle hook reads `self.app` instead, which is
typed as the concrete `TuiApp`. That is a deliberate trade: keeping `Host` at seven
methods is worth more than routing `scheduler` and `screens` through it, but it
does mean there are two channels rather than one. See Open work.

Dispatch precedence for one event is fixed:

1. capture hooks, root to target
2. capture-priority key bindings
3. the target widget's `handle`
4. bubble-priority key bindings
5. bubble hooks, target to root

The split exists so an application can reserve keys such as `ctrl_c` in the
capture phase while a composer keeps `tab` for completion by declining it in
the target phase. `Harness.dispatch` and `TuiApp.dispatch` are the same code path.

`core/screen.py` stacks layers: painting runs bottom to top, and the topmost
modal layer both traps input and becomes the focus scope. `core/focus.py`
handles Tab traversal and remembers the focus a pushed screen covered.
`core/scheduler.py` separates explicit repaint requests from animation ticks so
a busy widget can never drive the loop faster than `max_fps`. `core/keymap.py`
pairs a command registry with contextual bindings.

`runner.py` owns the real terminal. `TerminalRunner` enters raw mode, bridges
decoded input through `input/bridge.py`, paints on the scheduler's schedule,
and mirrors copied text to the system clipboard with an OSC 52 fallback;
`run_app` is the one-shot convenience wrapper around it. The class exists
because the loop has state worth naming and inspecting: the renderer, the input
queue, the wake-up event, and the long-lived reader task. Its module docstring
carries a sequence diagram of startup, the frame loop, the idle wait, and
shutdown.

## Layout

`layout/solver.py` is the only place that turns a constraint budget into
extents. `Track` describes one row or column as fixed, minimum, or flexible,
and `resolve_tracks` hands the leftover to flex tracks and scales everything
down proportionally when the fixed sizes alone overflow.

`layout/box.py` builds `VBox` and `HBox` on that solver. `layout/spacing.py`
adds `Padding` and `Border`, `layout/overlay.py` adds `Anchor` and `Overlay`
for anchored placement, and `layout/scroll.py` adds `ScrollView`. An `Anchor`
either aligns the child's measured size (`start`, `center`, `end`) or fills the
parent (`stretch`), and an explicit `width`/`height` overrides both.

Containers do not forward input: `core` routing already targets the deepest
widget, so a box that also handled events would deliver each one twice.

`ScrollView` is virtualized. It asks its `LineSource` for `count(width)`, which
must be cheap, and then calls `line(index, width)` only for rows that are
actually on screen. Because the source returns already-wrapped lines, the view
never has to measure the whole document.

Scroll position is an absolute line index rather than a distance from the
bottom, which is what makes anchoring work: appending content leaves the view
untouched while the reader is scrolled up, and `adjust_for_insertion` shifts
the window when lines are inserted above it so the same content stays visible.

`ScrollView` also owns text selection, because a selection is a range in the
same line-and-column space the window already works in. A drag records two
corners, rendering flips reverse video on the covered cells through
`Canvas.restyle`, and the copied text is sliced from the line sources with
`slice_columns`. Double-click selects a whole line, shift-click extends, and
dragging past an edge scrolls. Any widget over a `LineSource` gets this by
passing `selectable=True`.

## Widgets

| Widget | Role |
|---|---|
| `ListView` | Selectable rows with a scrolling window and disabled-row skipping |
| `TextArea` | Multi-line editor: Readline editing, undo, kill/yank, history, completion |
| `Dialog` | Bordered body plus selectable actions, meant for a modal screen |
| `Table` | Columns with alignment and truncation that fit the rectangle |
| `CompletionPopup` | Borderless candidate list the editor drives without taking focus |
| `StatusBar` | Left and right segments on one row |
| `Spinner` / `ProgressBar` | Indeterminate and determinate activity |
| `Toast` | Timed notice that dismisses its own screen when it expires |
| `Collapsible` | Header that reveals one child |
| `DiffView` | Unified diff with a line-number gutter and word-level emphasis |
| `Markdown` / `MarkdownView` | Streamed Markdown with incremental parsing |
| `Text` / `Rule` | Label and horizontal separator |
| `TaskPanel` | Ordered tasks with one in progress; empty panels take no rows |

Two conventions make these cooperate with the runtime. A widget that changes
its own layout calls `host.request_layout()`, because the app only re-runs
layout when asked. A widget that needs the clock implements `on_tick`, which
`TuiApp.tick` calls for every mounted widget before painting and which the runner
and the harness both invoke.

Every widget above also has a gallery sample. `make demo` opens a browser: an
index on the left lists the components and a pane on the right renders the
highlighted one, Enter hands the keyboard to a focusable preview, Escape gives
it back, and `q` quits. `make demo-<name>` prints one component's frame instead
and `make demo-all` prints every one, so a quick look needs no terminal.

The samples live in `tui/gallery.py`, where an entry is a name, a
size, and a factory. The browser mounts that factory as a screen layer, and
`render_entry` paints the same entry headlessly, so the interactive look and
the golden tests share one definition.

`TextArea` and `CompletionPopup` are deliberately split: the popup never takes
focus, so Tab and Enter keep belonging to the text being typed while the popup
only renders the candidates the editor reports.

## Rich content

`widgets/diff.py` parses unified diffs into typed rows and pairs each run of
removals with the additions that follow it. Paired lines go through a token
level `SequenceMatcher`, so only the tokens that actually changed are marked;
unpaired lines are marked whole. `build_unified` produces the diff text and
feeds the same parser, which keeps one code path for both entry points.

`widgets/markdown.py` parses incrementally. Text is split at blank lines that
are not inside an open code fence; every closed block is rendered once and
appended to a cached prefix, and only the trailing open block is re-rendered as
more text arrives. Repeated frames with unchanged text do no parsing at all,
which is what keeps a streamed answer linear instead of quadratic in its own
length. A single block with no blank line inside it still streams into the open
tail, so it is re-rendered until it closes.

`Markdown` doubles as a `LineSource` through `MarkdownSource`, so a document can
live inside the virtualized `ScrollView`: `count` and `line` come from the
cached prefix plus the open tail, and only the visible rows are ever built.
`MarkdownView` wires the two together and follows the tail while streaming.

## The application

`src/zettcode/app/` is the only consumer of the framework, and the only place
that knows about agents, sessions, and tools.

`transcript.py` holds the semantic model. `TranscriptSource` is a `LineSource`
over the entries that renders each entry at most once: every entry caches its
rendered block against a key of width, theme, expansion, status, and text
length, so an unchanged transcript costs nothing to repaint. Answer entries
delegate to `Markdown` instead of caching a flat list, which is what keeps a
streamed answer linear rather than quadratic.

`projection.py` maps `zett-agent` callbacks onto transcript blocks. Every
callback returns immediately, including the approval one: the agent is already
suspended waiting for the response the UI emits later, so a callback that
awaited the user would deadlock the stream. The approval callback opens a
bottom panel that asks the question in the transcript's own voice: the exact
command, shell-highlighted under a ``$`` prompt, above numbered choices that
name their keys — run once (``y``), always allow this command (``p``, only when
the runtime can remember one), auto mode (``a``, stop asking for the rest of
the run), or abort (``esc``). Arrows, Enter, the number keys, and clicks all
pick a row, and Escape aborts. Auto mode flips the runtime's approval extension
off rather than persisting a session policy, so the next launch reviews
commands again.

`app/agent/title.py` names a session after its first exchange: one provider
request with no tools, whose reply is reduced to a single line and written into
the workspace's `metadata.jsonl`, so renaming appends a line to the index and
never enters the conversation log. The shell schedules that call in the
background once a turn ends, which keeps the composer responsive, and `/sessions` presents the
result as another bottom panel — one row per session, with the title padded into
a column, the age of the last change, and the short id so an untitled session is
still identifiable.

`app/ui/app.py` assembles the header, transcript, composer, and status line,
and owns the keymap, the slash commands, the approval panel, and the toasts. Two
bindings show why the framework distinguishes capture from bubble priority:
`ctrl_c` and `ctrl_d` are captured, so the application can interrupt or exit
before the composer sees the key, while `page_up` and `page_down` are bubble
bindings that only run because the composer declines them.

The status line, transcript chrome, and every widget read colors from
`Theme` tokens, which is why `/theme dark|light` is a data change rather than a
repaint of hardcoded constants.

Code is highlighted but never filled: fenced blocks and inline code use a
foreground colour only, because a background block reads as a solid rectangle in
a terminal and fights the text. Inline code takes the palette's highlight green,
so `` `file.py` `` reads the same colour as the accent chrome around it.
`render/code.py` owns a small line tokenizer: Python keywords, strings,
comments, numbers, and called names, a shell mode that colours commands after
`&&`/`|` and leaves redirection targets plain, and a generic mode for everything
else. A `CodeTheme` supplies every colour. The tokenizer picks no colours
itself, so a palette stays data: `theme_file.py` loads `base`, `[ui]`, and
`[code]` tables from TOML, validates every key, and rejects anything it does not
understand rather than quietly falling back.

The plan panel above the composer is a `TaskPanel` with no framework knowledge
of tasks: the application polls `TodoWriteExtension.todos(session)` after every
streamed event and hands the panel a list of `(state, label)` pairs. An empty
panel measures zero rows, so it costs nothing until the agent publishes a plan.

`begin_turn` also inserts a placeholder entry. A model can take seconds to emit
its first token, and an empty transcript reads as a hung application, so the
placeholder animates and counts up from the moment Enter is pressed. It is not a
separate concept in the model: `start_thinking` converts it into the real
thinking row in place, and `drop_pending` removes it when the answer or a tool
call arrives first. Only rows whose status is `running` include the animation
frame in their cache key, so a completed transcript is never re-rendered just
because the clock moved.

## Hardening

`testing/snapshot.py` serializes a frame into trimmed text plus the styled runs
that are not default, so a color change is caught alongside a layout change.
Golden tests keep their expected block inline in the test module: a golden that
wrote its own reference file would need write access to the checkout, which
tests here must not have.

The first golden run found a real defect: `difflib` appends its own terminator
to diff headers, so joining with a newline inserted blank rows that parsed as
context lines and shifted every following line number.

`tests/test_input_fuzz.py` feeds randomized fragmentations of the same byte
stream and requires an identical event sequence. It found a second defect:
decoding byte by byte resolved `ESC [` as Alt-`[` before the rest of
`ESC [ < ... M` arrived. The decoder now waits on an `ESC [` or `ESC O` prefix
and lets the timeout resolve it, so an unknown control sequence is never
mistaken for a key press.

Performance is asserted with counters rather than timings wherever possible:
`tests/test_performance.py` records which transcript entries were rendered and
requires zero re-renders for an unchanged frame and for entries that only
streamed answer text. Two generous wall-clock ceilings cover the first paint of
a large transcript and repeated paints of an unchanged one.

Reduced motion is a first-class setting: `TuiApp.reduced_motion` stops decorative
animation, `Spinner` renders a static frame and never registers an animation
token, and the transcript stops advancing its activity counter. It is wired to
`--reduced-motion` and the `ZETTCODE_REDUCED_MOTION` environment variable.

`testing/` holds the headless harness. `Harness` mounts a widget tree at a
synthetic size, feeds `KeyEvent`/`TextEvent`/`PasteEvent`/`MouseEvent`/
`ResizeEvent`, and paints through the real `Canvas` and `DifferentialRenderer`.
`Snapshot` exposes fixed-width `lines`, styled `styled` runs, the `cursor`, and
trailing-trimmed `text` for readable assertions.

## Capability target

The framework must be able to support the interaction set a terminal coding
agent of Codex's class needs. That means the framework supplies the primitives,
not the policy:

| Area | Required capability |
|---|---|
| Rendering | Damage tracking, per-widget caches, virtualized viewports |
| Overlays | Screen/Layer stack, modal focus trapping, z-order |
| Focus | Focus tree, Tab traversal, scopes, restore on pop |
| Keys | Contextual keymap, command registry, user overrides |
| Events | Capture, target, bubble, with cancellable delivery |
| Layout | Constraint solving, padding and borders, anchored overlays |
| Widgets | List, Dialog, TextArea, Table, Diff, Markdown, Completion, StatusBar, Toast, Collapsible |
| Theme | Semantic tokens with multiple themes |
| Terminals | Truecolor/256 fallback, Unicode width, keyboard protocol, mouse, focus reporting |
| Testing | Headless driver, golden snapshots, decoder fuzzing |

Scenarios the framework must carry: approval dialogs, plan/todo panels, file
diff review, command palette and `@`-mention completion, a multi-line composer,
and a status line. Each is application policy expressed with framework
primitives.

One transitional inversion is worth naming: the legacy `input/events.py`
imports `MouseAction` from `core/events.py`, even though input sits below core.
It disappears in M2 when the legacy `InputEvent` model is deleted and the
decoder emits `core.events` directly.

## Testing strategy

The framework is only maintainable if it is verifiable without a real terminal.

- The headless harness drives a tree with deterministic events and a
  controllable clock, then snapshots the painted canvas.
- Golden snapshots freeze each widget's key states so rendering changes show up
  as reviewable diffs.
- Property tests assert width invariants for wrapping and truncation across CJK,
  emoji, and combining marks.
- Decoder fuzz tests assert that randomly split byte streams produce the same
  event sequence as unsplit input.

## Roadmap

Each milestone leaves the framework compiling, tested, and green under
`make check`. The existing application keeps working throughout via thin
compatibility shims at the old import paths.

**M0 - Contracts and skeleton.** Public API, `Widget` protocol, event model,
geometry, package layout, and the headless harness. *(done)*

**M1 - Substrate consolidation.** Move `terminal`, `input`, and `render` into
their final subpackages, add capability detection and truecolor fallback, and
add one Unicode text module for width, wrapping, and truncation. *(done)*

**M2 - Core runtime.** `TuiApp` loop, screen and layer stack, focus tree,
capture/bubble event routing, keymap and command registry, a frame scheduler
with an animation budget, and theme tokens. *(done)*

**M3 - Layout system.** Constraint solving, padding and borders, anchored
overlays, and a `ScrollView` with virtualization and stable scroll anchoring.
*(done)*

**M4 - Widget library v1.** List and menu, modal dialog, readline-grade
`TextArea`, table, completion popup, status bar, spinner, toast, and
collapsible. *(done)*

**M5 - Rich content.** `DiffView` with word-level highlighting and a
streaming-safe `Markdown` view that parses incrementally instead of re-parsing
the whole block every frame. *(done)*

**M6 - Interaction parity.** Approval dialogs, plan/todo panel, status line,
notifications, configurable keybindings, and theme switching. *(partly done:
approvals, plan panel, status line, notifications, and theme switching shipped;
user-editable keybindings are still open)*

**M7 - Hardening.** Golden snapshots, decoder fuzzing, frame-time benchmarks,
and reduced-motion support. *(done)*

## Open work

- User-editable keybindings. The keymap and command registry support it; nothing
  loads bindings from a configuration file yet.
- Pointer-leave collapse of thinking blocks. Clicking a row toggles it; there is
  no hover behavior now that entries are virtualized.
- One channel instead of two. `Host` carries input-time capabilities while
  lifecycle hooks use the concrete `widget.app` for the scheduler, screens, and
  `reduced_motion`. Unifying them means widening `Host` to roughly a dozen
  methods and typing `widget.app` as the interface.

## Decisions

1. The package stays `tui`, split into internal subpackages.
2. It stays in this repository but is organized so it could be extracted; it
   never imports `zettcode.*`.
3. The current application keeps running during M0-M3 through compatibility
   shims rather than a freeze-and-migrate rewrite.
4. `Markdown` and `Diff` live in the framework as generic rich-content widgets.
5. "Codex level" means the framework supports the interaction set above; the
   framework itself never implements the policy behind it.
