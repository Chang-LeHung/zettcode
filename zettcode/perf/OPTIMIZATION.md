# Performance round: what changed and what it bought

Recorded 2026-10-06 · Apple M4 / Darwin arm64 · CPython 3.14.0

The symptom: after pressing Enter in the composer, the paragraph just submitted
took a while to appear, and it got worse the more turns the session had; typing
also felt sticky while a reply streamed.

## Summary

| # | Hot spot | Before | After | Change |
| --- | --- | --- | --- | --- |
| 1 | Every animation frame invalidated the whole transcript cache | Busy-frame cost grew with turns: `0.052 ms` at 20 turns to `1.735 ms` at 1200 | `0.004 ms` to `0.141 ms` | `advance_frame` returns when the step is unchanged; `take_dirty` + `TranscriptSource._sync` re-measure only the dirty suffix |
| 2 | Every streamed token re-measured every entry | `0.90 ms` at 10 turns to `2.96 ms` at 1600 (per token + frame) | `0.86 ms` to `0.89 ms`, **flat** | `TranscriptSource._sync` (src/zettcode/app/ui/widgets/transcript.py:86) |
| 3 | `advance_frame` scanned every entry each step | tick: `3.8 us` at 400 turns to `18.6 us` at 1600 | `3.5 us`, **flat** | `Transcript.advance_frame` (src/zettcode/app/agent/transcript.py:171) walks back from the tail and stops at the first settled row |
| 4 | Every append re-parsed the whole session JSONL | At 150 messages: append `38.2 ms`/message, read `77.2 ms` | append `0.79 ms`/message (cold-cache amortized), read `0.006 ms`; still `0.11 / 0.006 ms` at 3000 | `SessionStore.read` + `_remember` (src/zettcode/app/agent/storage/store.py:187) cache by file stat and fold in each written line |
| 5 | No display cap on the transcript | ~20k entries at 5000 turns; resize first frame `274 ms` at 1600 turns and unbounded | entries stay <= 1056; resize first frame `~46 ms`, flat | `[transcript] max_entries` (default 1024) + `Transcript._trim` (transcript.py:110) wired in `ZettCodeApp` |

The acceptance bar is **a flat curve, not a small number**: the terminal window
is bounded, so a frame must not get slower because the session got longer. The
absolute values depend on terminal size and machine.

## Detail

### 1. An animation frame invalidated the whole transcript

`advance_frame()` bumped `version += 1` on every frame, and the terminal calls it
up to 120 times a second while a request runs. The view uses `version` as its
cache key, so **every painted frame walked every entry** and rebuilt the block
boundaries; the cost grew linearly with the session. That is exactly the
"submit lag that gets worse with turns".

- First, a tick that falls inside the animation step it already sits on stops
  bumping the version.
- Then the model records which entries changed: `take_dirty()` returns the
  earliest dirty index, and the view re-measures only that suffix, reusing the
  prefix blocks as they are. Only a width, theme, or processor change forces a
  full rebuild.

### 2. O(N) re-measure per streamed token

`append_answer` bumps the version for every token, which triggered a full
re-measure. cProfile (1600 turns, 400 streamed frames) showed
`TranscriptSource._sync` taking **88% of the time (3.68 s of 4.19 s)**. After
the incremental rebuild the same scenario takes **1.05 s**, and `_sync` no
longer appears near the top.

### 3. `advance_frame` itself was O(N)

Running rows always sit at the tail of the list — a row is appended when it
opens, and a result closes its row before anything new lands. Scanning back
from the end and stopping at the first non-running entry makes the animation
step independent of session length.

### 4. O(N) re-parse per session append

`append()` called `read()`, which parsed and validated the whole file with
pydantic; at 150 messages a read cost 77 ms, so each append cost 38 ms and
writing a session was O(N^2). The store now caches the parsed session keyed by
`(mtime_ns, size)` and folds each written line into the cache, so the append
that just happened never pays for a re-parse. The file format and its contents
are unchanged.

### 5. Display cap

`data.jsonl` keeps the whole conversation tree, and the model still receives the
full active branch; the cap only limits **how far the reader can scroll back**.
Overflow is dropped from the front in batches: the list may grow to
`max_entries + max(8, max_entries // 32)` before a trim takes it back to
`max_entries`, which amortizes the list shift and the view rebuild. The default
is `1024`, configurable in `~/.zettcode/config.toml`:

```toml
[transcript]
max_entries = 1024
```

Measured kept entries: 1036 at 300 turns, 1038 at 2000, 1026 at 5000. The
resize first frame is therefore stable near 46 ms instead of growing with the
session.

## Measurement setup

Two harnesses were used; every before/after pair was measured inside the *same*
one, so no comparison crosses a change of setup.

| Setup | Used for |
| --- | --- |
| Early ad-hoc scripts | Driving `TranscriptSource` / an offline fake app directly; before/after for items 1, 2, 3, 4 |
| `perf/` probes | The real shell, offline, hand-driven clock, per-stage timing (`dispatch/layout/tick/paint/cursor/diff`) at 120x40; items 3 and 5, and the final baseline |

## Known boundaries (not addressed this round)

- A steady frame is still about 2.0 ms at 120x40: `paint` ~1.55 ms plus `diff`
  ~0.44 ms. Both scale with the **visible screen area**, not with turns. Cutting
  them further means changing the canvas layer (a fresh canvas and a per-cell
  comparison every frame).
- The first frame after a terminal resize still re-wraps every kept entry to
  learn the new total height; that is O(kept entries), now bounded by the
  display cap.

## Reproduce

```bash
uv run python -m perf.frame_stages --turns 200 --frames 200   # per-stage cost
uv run python -m perf.scaling --turns 10,100,400,1600         # vs turns (must be flat)
uv run python -m perf.store --messages 200,800,3000           # append/read cost
uv run python -m perf.profile --scenario stream --turns 1600  # cProfile hot spots
```

The full baseline numbers live in [`RESULTS.md`](RESULTS.md).
