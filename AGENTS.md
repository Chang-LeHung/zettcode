# Development Rules

## Scope

The repository is a uv workspace of two packages, and the root `pyproject.toml` is only the workspace: the shared
tool configuration (Ruff, mypy, the dev dependency group) and the member list. Nothing is published from the root.

- `zettcode/` is the terminal coding agent. `src/zettcode` holds `cli.py` and
  `config.py` at the top, the application in `app/` (`agent/` for the
  conversation model, the event projection, session persistence, and the
  runtime composition, grouped into `agent/` itself — the one class, built
  from mixins — and `conversation/`, `dialogue/`, `extensions/`,
  `permission/`, `storage/`, `export/` and `runtime.py`; `docs/internal/tui.md`
  has the map and `tests/test_structure.py` the import order; `ui/` for the
  shell and the views), and the reusable framework in `tui/`; `tests` drives
  all of it without a real terminal. The session broker is `broker/`: one small
  package, a Starlette application served by uvicorn on loopback (sessions are
  WebSockets, sending is `POST /messages`, any process with the token may use it)
  and the client a session reaches it with; there is no RPC layer of our own in
  it, and none should be added.
- The agent runtime is an external dependency: depend on released `zett-agent`
  versions and never vendor or re-implement the model loop, tools, compaction,
  or message types. Session persistence is the deliberate exception —
  `app/agent/` owns the storage format *and* the lifecycle adapter that drives
  it, built only on the released hook contract and context/event types, so
  storage policy moves with this repository.
- The TUI owns the terminal. Raw mode, input decoding, layout, and differential
  cell rendering live in `zettcode/src/zettcode/tui`; do not add prompt-toolkit
  or another TUI framework.
- `zettcode-server/` is the HTTP face of the same agent, and holds no agent of its own: every endpoint drives
  `zettcode.sdk`, which drives the released `zett-agent` runtime. It is one process per workspace, because the SDK
  keeps the process's working directory. Do not re-implement tools, sessions, model calls, or the SDK's event
  translation there; add a method to the SDK first when the server needs something it does not have.
- Keep Zett application vocabulary (artifacts, tags, cards, channels, scheduled
  tasks) out of this repository. ZettCode is a coding agent, not a host app.

## Tooling

- Python 3.10+ and `uv` for dependency management; Ruff for formatting and
  linting with `line-length = 120`, and mypy for the shipped code of both packages under
  `zettcode/src`, `zettcode/perf` and `zettcode-server/src`. Both tools target 3.10 and CI runs 3.10 through 3.14, so
  keep the source free of newer syntax and standard-library APIs; the version shims live in
  `zettcode/src/zettcode/_compat.py`.
- Run `make check` (Ruff, mypy, and both test suites) before handing work over, and
  `make smoke` when packaging changes so each console script is exercised from the built wheels.
- Run `make hooks` once per checkout: the installed pre-commit hook runs mypy
  and refuses a commit that does not type-check. Keep `make check` green rather
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

- The version of the agent lives in `zettcode/src/zettcode/__init__.py`; `zettcode/pyproject.toml` asks hatchling to
  read it from there, and a release is a commit that sets it plus a `v<version>` tag. The release workflow reads the
  same file and refuses to publish when the tag and it disagree. `zettcode-server` has its own version in
  `zettcode-server/src/zettcode_server/__init__.py` and is not published by that tag.
- A `zettcode-server` release must keep its `zettcode>=` floor at the version whose SDK it was built against, the
  same rule `zett-agent` follows below.
- Publishing requires the `PYPI_API_TOKEN` repository secret; see `RELEASING.md`.
- When `zett-agent` is released, raise the `zett-agent` floor in the same change
  — the dependency is a range (`>=0.1.13,<0.2`), never an exact pin, because
  zettcode shares that dependency with other tools — re-lock, and run
  `make check` before tagging.
