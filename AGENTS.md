# Development Rules

## Scope

- ZettCode is the terminal coding agent. `src/zettcode` holds `cli.py` and
  `config.py` at the top, the application in `app/` (`agent/` for the
  conversation model, the event projection, session persistence, and the
  runtime composition; `ui/` for the shell and the views), and the reusable
  framework in `tui/`; `tests` drives all of it without a real terminal.
- The agent runtime is an external dependency: depend on released `zett-agent`
  versions and never vendor or re-implement the model loop, tools, compaction,
  or message types. Session persistence is the deliberate exception —
  `app/agent/` owns the storage format *and* the lifecycle adapter that drives
  it, built only on the released hook contract and context/event types, so
  storage policy moves with this repository.
- The TUI owns the terminal. Raw mode, input decoding, layout, and differential
  cell rendering live in `src/zettcode/tui`; do not add prompt-toolkit
  or another TUI framework.
- Keep Zett application vocabulary (artifacts, tags, cards, channels, scheduled
  tasks) out of this repository. ZettCode is a coding agent, not a host app.

## Tooling

- Python 3.14+ and `uv` for dependency management; Ruff for formatting and
  linting with `line-length = 120`, and mypy for the shipped code under `src`.
- Run `make check` (Ruff, mypy, and pytest) before handing work over, and
  `make smoke` when packaging changes so the console script is exercised from
  the built wheel.
- Run `make hooks` once per checkout: the installed pre-commit hook runs mypy
  and refuses a commit that does not type-check. Keep `make check` green rather
  than bypassing the hook.
- Tests must never write into the checkout or into `~/.zettcode`. Use temporary
  directories and pass them explicitly.
- `docs/invariants.md` lists the rules the code depends on but types do not
  enforce, each marked done with the test that pins it or todo with what is
  missing. Adding a load-bearing rule means adding a row and a test; breaking
  one means the cited test fails, so keep the marks honest.
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

- The version lives in `pyproject.toml`; a release is a commit that sets the
  final version plus a `v<version>` tag. The release workflow refuses to publish
  when the tag and the project version disagree.
- Publishing requires the `PYPI_API_TOKEN` repository secret; see `RELEASING.md`.
- When `zett-agent` is released, bump the pinned `zett-agent==` dependency in the
  same change, re-lock, and run `make check` before tagging.
