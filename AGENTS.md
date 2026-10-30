# Development Rules

## Scope

The repository is a uv workspace of one package, and the root `pyproject.toml` is only the workspace: the shared
tool configuration (Ruff, mypy, the dev dependency group) and the member list. Nothing is published from the root.

- `zettcode/` is the terminal coding agent. `src/zettcode` holds `cli.py` and
  `config.py` at the top, the agent core in `engine/` (`ZettCodeEngine` in
  `core.py`, and the `dialogue/`, `extensions/`, `permission/`, `storage/`,
  `tools/`, `export/` it is built from, plus the messenger between sessions;
  it imports nothing of the terminal, the SDK or the server — `docs/internal/engine.md`
  has the design), the terminal application in `app/` (`agent/` for the
  conversation model and the event projection, `ui/` for the shell and the
  views; `docs/internal/tui.md` has the map and `tests/test_structure.py` the
  import order), and the reusable framework in `tui/`; `tests` drives
  all of it without a real terminal. The session broker is `broker/`: one small
  package, a Starlette application served by uvicorn on loopback (sessions are
  WebSockets, sending is `POST /messages`, any process with the token may use it)
  and the client a session reaches it with; there is no RPC layer of our own in
  it, and none should be added.
- The agent runtime is an external dependency: depend on released `zett-agent`
  versions and never vendor or re-implement the model loop, compaction, or
  message types. Two things are the deliberate exceptions. Session persistence —
  `engine/storage` owns the storage format *and* the lifecycle adapter that drives
  it, built only on the released hook contract and context/event types, so
  storage policy moves with this repository. And the coding tools (`read`,
  `read_file`, `glob`, `grep`, `write_file`, `edit`, `bash`), which are
  `engine/tools`: ours, fully type-hinted, registered through the framework's
  `@tool` and `AgentTool` contract but run by nothing from the framework. Do not
  import a tool from `zett_agent.tools.coding` or a file-system extension.
- A new interface between our own parts is an abstract base class, not a
  `typing.Protocol`: a subclass that forgets a method fails when it is built, and
  the implementation says what it implements. (`CommandHost`, `Peer`, `Bridge`
  and `SessionGuard` are older structural protocols that have not been
  converted.)
- The TUI owns the terminal. Raw mode, input decoding, layout, and differential
  cell rendering live in `zettcode/src/zettcode/tui`; do not add prompt-toolkit
  or another TUI framework.
- `zettcode-server` is the HTTP face of the same agent, in `src/zettcode/server/`, and holds no agent of its own:
  every endpoint drives
  `zettcode.sdk`, which drives the released `zett-agent` runtime. It ships in the same distribution as the terminal —
  `pip install zettcode` writes both console scripts — so `fastapi` is a core dependency, not an extra, and the two
  share one version. It is one process per workspace, because the SDK
  keeps the process's working directory. Do not re-implement tools, sessions, model calls, or the SDK's event
  translation there; add a method to the SDK first when the server needs something it does not have.
- `clients/typescript/` is the TypeScript client for the server, and only a client: it speaks the HTTP API, has no
  runtime dependency, and parses the event stream itself. A capability the client needs is an endpoint on the server
  first, never a shortcut through the SDK.
- `clients/vscode/` is the VS Code face of that server, and only a client: a webview chat that bundles the TypeScript
  client's source and speaks HTTP, never the SDK or the agent. The token, the server's process and every editor action
  live in the extension host; the webview posts messages and receives state. It also must not re-implement the event
  translation, sessions, or models — a missing capability is a server endpoint, then a TypeScript client method.
  `docs/internal/vscode.md` has the map and the rules its tests pin.
- Keep Zett application vocabulary (artifacts, tags, cards, channels, scheduled
  tasks) out of this repository. ZettCode is a coding agent, not a host app.

## Tooling

- Python 3.10+ and `uv` for dependency management; Ruff for formatting and
  linting with `line-length = 120`, and mypy for the shipped code under
  `zettcode/src` and `zettcode/perf`. Both tools target 3.10 and CI runs 3.10 through 3.15, so
  keep the source free of newer syntax and standard-library APIs; the version shims live in
  `zettcode/src/zettcode/_compat.py`.
- Run `make check` while working: it compares the tree with where the branch left `main` (`BASE=…` picks another
  ref) and runs only what the change touches — Ruff, mypy and the Python suite for `zettcode/`, the TypeScript
  client for `clients/typescript/`, the extension for either JavaScript client, and nothing for a guide-only edit.
  Run `make check-all` before handing work over; CI runs only the suites a pull request's diff needs — `zettcode/`,
  `uv.lock` and the root `pyproject.toml` for the Python gate, `clients/<name>/` for a client, `plugins/` or the
  `zettcode/` the plugin runs against for the plugin, and everything for the `Makefile` or a workflow — so a full run
  does not have to happen on every edit. Run `make smoke` when packaging changes so both console scripts are exercised
  from the built wheel. `make vscode`
  runs the extension's type-check, jsdom tests and build on its own, and `make vscode-package` writes a `.vsix`.
- Node 20+ builds both JavaScript clients. `clients/typescript` is dependency-free at runtime; `clients/vscode`
  has dev dependencies only (esbuild, TypeScript, jsdom) and bundles everything it runs into `dist/`.
- Run `make hooks` once per checkout: the installed pre-commit hook runs mypy
  and refuses a commit that does not type-check. Keep `make check-all` green rather
  than bypassing the hook.
- Tests must never write into the checkout or into `~/.zettcode`. Use temporary
  directories and pass them explicitly.
- `docs/internal/invariants.md` lists the rules the code depends on but types do
  not enforce, each marked done with the test that pins it or todo with what is
  missing. Adding a load-bearing rule means adding a row and a test; breaking
  one means the cited test fails, so keep the marks honest.
- `docs/` is the published user guide (VitePress, English at `/` and Chinese at
  `/zh/`); `docs/internal/` is ours and is excluded from the site. Keep
  implementation detail in `docs/internal/`, and write the guide for someone
  using the program.
- The terminal layer runs on POSIX and on Windows. The platform split lives in
  `tui/console.py`: `PosixConsole` uses `termios`/`tty`, `WindowsConsole` clears
  the console's cooked input flags and turns on virtual-terminal input, so the
  decoder and renderer stay platform-free. Keep the `termios`/`tty` imports
  inside the POSIX methods, keep the module importable on a machine with no
  console, and remember that a Windows console handle cannot be watched with
  `add_reader` — `AsyncInput` falls back to a reader thread there.

## Merging pull requests

- A one-commit pull request lands with
  `gh pr merge <n> --squash --delete-branch`: GitHub appends ` (#<n>)` to the
  generated subject, which is the `… (#28)` style the history is written in.
- A multi-commit pull request lands with `--rebase`. Rebase merge never adds the
  number, so before merging append ` (#<n>)` to the tip commit's subject (amend
  it and force-push the branch with `--force-with-lease`) to keep the pull
  request named in `git log`.

## Releases

- The version lives in `zettcode/src/zettcode/__init__.py`; `zettcode/pyproject.toml` asks hatchling to
  read it from there, and a release is a commit that sets it plus a `v<version>` tag. The release workflow reads the
  same file and refuses to publish when the tag and it disagree. The terminal and the server are one distribution and
  one version; there is no second tag.
- Publishing requires the `PYPI_API_TOKEN` repository secret; see `RELEASING.md`.
- When `zett-agent` is released, raise the `zett-agent` floor in the same change
  — the dependency is a range (`>=0.1.13,<0.2`), never an exact pin, because
  zettcode shares that dependency with other tools — re-lock, and run
  `make check` before tagging.
