// Replay of a past time window: pure functions over the stored messages (no Vue, no DOM). Nothing is re-sent; the
// view only draws what these functions say. "Real" time is epoch seconds of the stored history; "playback" time is
// seconds since the replay began on the viewer's clock, after speed and silence skipping.

import { pairKey } from "./graph";
import { reached } from "./graphData";
import type { GraphEdge, GraphMessage } from "../types";

export type Preset = "15m" | "1h" | "24h" | "7d" | "all";

/** The window choices, with their length in seconds (null: everything the history holds). */
export const presets: { id: Preset; label: string; seconds: number | null }[] = [
  { id: "15m", label: "15m", seconds: 900 },
  { id: "1h", label: "1h", seconds: 3600 },
  { id: "24h", label: "24h", seconds: 86400 },
  { id: "7d", label: "7d", seconds: 604800 },
  { id: "all", label: "All", seconds: null },
];

/** The window a preset names, ending at `now`; "all" starts at the oldest message (`span[0]`, or `now`). */
export function windowFor(
  preset: Preset,
  now: number,
  span: [number, number] | null,
): { since: number; until: number } {
  const seconds = presets.find((p) => p.id === preset)?.seconds ?? null;
  if (seconds === null) return { since: span ? Math.min(span[0], now) : now, until: now };
  return { since: now - seconds, until: now };
}

export interface Replay {
  /** Oldest first. */
  messages: GraphMessage[];
  /** The window, epoch seconds. */
  start: number;
  end: number;
  /** end - start, real seconds. */
  duration: number;
}

/** Keep the messages inside [since, until], sorted by time then id. */
export function buildReplay(messages: GraphMessage[], since: number, until: number): Replay {
  const end = Math.max(since, until);
  const kept = messages.filter((m) => m.ts >= since && m.ts <= end).sort((a, b) => a.ts - b.ts || a.id - b.id);
  return { messages: kept, start: since, end, duration: end - since };
}

/** Playback seconds that a silence is squeezed to. */
export const MAX_GAP = 2;

/** The speed that plays the whole window in 30 seconds ("fit30"). */
export function fit30(replay: Replay): number {
  return Math.max(replay.duration / 30, 1e-6);
}

export interface Segment {
  r0: number;
  r1: number;
  /** Playback position at each end. */
  p0: number;
  p1: number;
  /** A silence that was squeezed. */
  skipped: boolean;
}

export interface Clock {
  segments: Segment[];
  /** Playback seconds the whole window takes. */
  playbackDuration: number;
  /** Playback position -> real time (clamped to the window). */
  toReal(playbackT: number): number;
  /** Real time -> playback position (clamped). */
  toPlayback(realT: number): number;
  /** Real seconds of silence squeezed away before `realT`. */
  skippedBefore(realT: number): number;
}

/**
 * Map real time to playback time. Each stretch plays at `speed`; with `skip`, a gap between consecutive messages (or
 * the window's ends) longer than `maxGap * speed` real seconds takes just `maxGap` playback seconds.
 */
export function compress(replay: Replay, speed: number, skip: boolean, maxGap = MAX_GAP): Clock {
  const rate = speed > 0 ? speed : 1;
  const points = [replay.start, ...replay.messages.map((m) => m.ts), replay.end];
  const segments: Segment[] = [];
  let p = 0;
  for (let i = 1; i < points.length; i++) {
    const r0 = points[i - 1] as number;
    const r1 = points[i] as number;
    if (r1 <= r0) continue;
    const skipped = skip && r1 - r0 > maxGap * rate;
    const len = skipped ? maxGap : (r1 - r0) / rate;
    segments.push({ r0, r1, p0: p, p1: p + len, skipped });
    p += len;
  }
  const total = p;
  const toPlayback = (realT: number): number => {
    if (realT <= replay.start) return 0;
    for (const s of segments) {
      if (realT <= s.r1) return s.p0 + ((realT - s.r0) / (s.r1 - s.r0)) * (s.p1 - s.p0);
    }
    return total;
  };
  const toReal = (t: number): number => {
    if (t <= 0) return replay.start;
    for (const s of segments) {
      if (t <= s.p1) return s.r0 + ((t - s.p0) / (s.p1 - s.p0)) * (s.r1 - s.r0);
    }
    return replay.end;
  };
  const skippedBefore = (realT: number): number => {
    let sum = 0;
    for (const s of segments) {
      if (!s.skipped) continue;
      const upto = Math.min(realT, s.r1);
      if (upto <= s.r0) break;
      const squeezed = (s.r1 - s.r0) / rate - (s.p1 - s.p0);
      sum += squeezed * rate * ((upto - s.r0) / (s.r1 - s.r0));
    }
    return sum;
  };
  return { segments, playbackDuration: total, toReal, toPlayback, skippedBefore };
}

export interface ReplayState {
  /** Every message with ts <= realT. */
  shown: GraphMessage[];
  /** One-to-one totals of `shown`, a = sender, b = the one reached. */
  edges: GraphEdge[];
  /** Senders and recipients of `shown` only. */
  shownIds: Set<string>;
  /** shownIds plus everyone in the whole window, so nodes do not pop in. */
  sessionIds: Set<string>;
  /** Names of the groups that `shown` messages went to. */
  groupsTouched: Set<string>;
}

/** Everything the graph shows when the playhead is at `realT`. Recomputed from scratch, so scrubbing back shrinks it. */
export function stateAt(replay: Replay, realT: number): ReplayState {
  const shown = replay.messages.filter((m) => m.ts <= realT);
  const edges = new Map<string, GraphEdge>();
  const shownIds = new Set<string>();
  const groupsTouched = new Set<string>();
  for (const m of shown) {
    shownIds.add(m.from.session_id);
    for (const id of m.recipients) shownIds.add(id);
    if (m.to.kind === "group" && m.to.name) groupsTouched.add(m.to.name);
    const target = m.to.kind === "session" ? reached(m)[0] : undefined;
    if (!target) continue;
    const key = pairKey(m.from.session_id, target);
    const edge = edges.get(key);
    if (edge) {
      edge.count += 1;
      edge.last = Math.max(edge.last, m.ts);
    } else {
      edges.set(key, { a: m.from.session_id, b: target, count: 1, last: m.ts });
    }
  }
  const sessionIds = new Set(shownIds);
  for (const m of replay.messages) {
    sessionIds.add(m.from.session_id);
    for (const id of m.recipients) sessionIds.add(id);
  }
  return { shown, edges: [...edges.values()], shownIds, sessionIds, groupsTouched };
}

/** The messages passed while the playhead moved from `fromRealT` (excluded) to `toRealT` (included). */
export function due(replay: Replay, fromRealT: number, toRealT: number): GraphMessage[] {
  return replay.messages.filter((m) => m.ts > fromRealT && m.ts <= toRealT);
}

/** The messages of the last `seconds` up to `realT`, to light up after a seek. */
export function recentTail(replay: Replay, realT: number, seconds: number): GraphMessage[] {
  return replay.messages.filter((m) => m.ts <= realT && m.ts > realT - seconds);
}

/** Message counts in `buckets` equal slices of the window, for a sparkline. */
export function histogram(replay: Replay, buckets: number): number[] {
  const n = Math.max(1, Math.floor(buckets));
  const counts = new Array<number>(n).fill(0);
  for (const m of replay.messages) {
    const i = replay.duration > 0 ? Math.floor(((m.ts - replay.start) / replay.duration) * n) : 0;
    const at = Math.min(n - 1, Math.max(0, i));
    counts[at] = (counts[at] ?? 0) + 1;
  }
  return counts;
}

const two = (n: number): string => String(n).padStart(2, "0");

/** The local time of day, "14:05:09". */
export function formatClock(ts: number): string {
  const d = new Date(ts * 1000);
  return `${two(d.getHours())}:${two(d.getMinutes())}:${two(d.getSeconds())}`;
}

/** A length of time: "45s", "12m", "3h 12m", "2d 4h". */
export function formatSpan(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return m % 60 ? `${h}h ${m % 60}m` : `${h}h`;
  const d = Math.floor(h / 24);
  return h % 24 ? `${d}d ${h % 24}h` : `${d}d`;
}
