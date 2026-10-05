# Performance probes

Reusable, reproducible measurements of ZettCode's hot paths. They are not
tests: they build the real application offline (no provider, no network, no
`~/.zettcode`) and print wall time, so a performance claim can be re-checked
after every change instead of trusted.

## How it works

- `harness.py` builds a real shell from `ZettCodeRuntime.preview(config)` — the
  same seam the shell uses to paint before the provider exists — against a
  throwaway workspace and store under the system temp directory. Nothing is
  written into the checkout or `~/.zettcode`.
- The transcript is seeded directly through its public API with finished turns
  (user, reasoning, tool call and result, Markdown answer) so the block types
  match a real session. `busy=True` leaves a trailing running row.
- `Painter` mirrors `TerminalRunner.paint` stage for stage, minus the terminal
  and minus the test harness's snapshot pass, and times each stage: `dispatch`,
  `layout`, `tick`, `paint`, `cursor`, `diff`.
- A hand-driven `Clock` makes animation steps deterministic, so results do not
  depend on how fast the machine happens to run.

## Probes

| Command | Answers |
| --- | --- |
| `uv run python -m perf.frame_stages` | Which stage of a frame costs what, for typing, animation, streaming, and the first frame after a resize. |
| `uv run python -m perf.scaling` | Does a frame get slower as the transcript grows? The columns must stay flat. |
| `uv run python -m perf.profile --scenario stream` | Which function dominates a scenario, by cProfile self time. |
| `uv run python -m perf.store` | Is a session append or read O(N) in the log length? The columns must stay flat. |

Common flags: `--turns` (transcript size), `--frames` (samples to average),
`--width`/`--height` (synthetic terminal size; default `120x40`).

## Reading the numbers

- **Flat, not small, is the acceptance bar.** The terminal window is bounded,
  so a frame must not get slower because the session got longer. A rising
  column is the bug; the absolute value depends on terminal size and machine.
- `paint` scales with the *visible* screen area (`width x height`) and is
  expected to dominate on a large terminal. `diff` likewise. Neither should
  track `--turns`.
- The first frame after a resize is different: a width change re-wraps every
  entry to learn the new total height, so that one frame is O(kept entries).
  The display cap (`[transcript] max_entries`, or `Transcript(max_entries=…)`)
  bounds it, which is why it stops growing once a session is longer than the
  cap; keep that in mind before blaming a resize hitch on the steady state.
- Compare runs on the same machine and terminal size. Use `profile.py` to turn a
  rising stage into a named function.

Recorded numbers live in [`RESULTS.md`](RESULTS.md), with the date and machine
so a later run can be compared fairly. [`OPTIMIZATION.md`](OPTIMIZATION.md)
summarizes one round: what was slow, what changed, and the before/after numbers.
