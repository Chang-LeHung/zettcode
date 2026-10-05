# Recorded results

Baseline captured on 2026-10-05 so later runs have something to compare
against. Re-run the same command with the same flags on the same machine.

- Machine: Apple M4, Darwin arm64
- Runtime: CPython 3.14.0
- Synthetic terminal: `120x40`

## Frame stages

`uv run python -m perf.frame_stages --turns 200 --frames 200`

Microseconds per frame; `paint` and `diff` scale with the visible screen, not
the session, so this is the baseline for the terminal size above.

| scenario | dispatch | layout | tick | paint | cursor | diff | total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| typing | 20.6 | 0.2 | 3.2 | 1537.7 | 0.3 | 441.1 | 2003.0 |
| animating | 0.0 | 0.0 | 3.5 | 1632.0 | 0.3 | 424.8 | 2060.5 |
| streaming | 0.0 | 0.0 | 3.3 | 2017.2 | 0.2 | 515.0 | 2535.8 |
| resize (first frame) | 0.0 | 23.8 | 5.4 | 35782.5 | 0.5 | 453.8 | 36266.0 |

`paint` dominates and is flat in transcript size; `diff` is next. The resize
frame re-wraps every entry when the width changes and is not part of the steady
state; it is O(kept entries) and therefore bounded by `[transcript] max_entries`
(the default 1024 caps it near 46 ms however long the session gets, versus
274 ms at 1600 uncapped turns).

## Scaling

`uv run python -m perf.scaling --turns 10,100,400,1600 --frames 200`

Milliseconds per interaction. The acceptance bar is flat columns.

| turns | typing | animating | streaming |
| ---: | ---: | ---: | ---: |
| 10 | 2.037 | 2.069 | 2.530 |
| 100 | 2.055 | 2.062 | 2.567 |
| 400 | 2.100 | 2.109 | 2.624 |
| 1600 | 2.124 | 2.221 | 2.719 |

## Session store

`uv run python -m perf.store --messages 200,800,3000 --repeats 20`

Milliseconds per operation. Both columns must be flat in the log length.

| messages | append ms | read ms |
| ---: | ---: | ---: |
| 200 | 0.587 | 0.006 |
| 800 | 0.106 | 0.006 |
| 3000 | 0.114 | 0.006 |

The first row is amortized cold-cache cost; the steady state is the third.

## Display cap

`[transcript] max_entries` (default `1024`) keeps the entries on screen bounded.
Measured kept entries: 300 turns -> 1036, 2000 -> 1038, 5000 -> 1026 (the batch
trim may hold up to `max_entries + max(8, max_entries // 32)` before dropping
back). The session file is untouched, so this bounds scrollback only.

## Fixed regressions

Kept here so the same mistakes are recognizable.

- **Full-transcript re-measure per frame/token.** `TranscriptSource._sync`
  rebuilt every block boundary whenever the transcript version moved, and a
  running or streaming row moved it every frame. Streaming cost grew
  0.9 ms/token at 10 turns to 2.96 ms at 1600 (measured before the incremental
  fix; `Transcript.take_dirty` now narrows the rebuild to the changed suffix).
- **Full session re-parse per append.** `SessionStore.append` called `read`,
  which parsed and validated the whole JSONL file. At 150 messages a read cost
  **77 ms** and each append **38 ms**; with the stamp-keyed cache it is
  **0.006 ms** and **0.11 ms**, flat at 3000 messages.
