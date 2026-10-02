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
  linting with `line-length = 120`.
- Run `make check` (Ruff plus pytest) before handing work over, and `make smoke`
  when packaging changes so the console script is exercised from the built wheel.
- Tests must never write into the checkout or into `~/.zettcode`. Use temporary
  directories and pass them explicitly.
- Keep the terminal layer importable off POSIX: `termios`/`tty` imports stay
  inside the raw-mode methods and report a clear error elsewhere.

## Releases

- The version lives in `pyproject.toml`; a release is a commit that sets the
  final version plus a `v<version>` tag. The release workflow refuses to publish
  when the tag and the project version disagree.
- Publishing requires the `PYPI_API_TOKEN` repository secret; see `RELEASING.md`.
- When `zett-agent` is released, bump the pinned `zett-agent==` dependency in the
  same change, re-lock, and run `make check` before tagging.
