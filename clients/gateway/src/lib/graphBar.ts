// Small pure helpers of the replay bar and of the graph in replay mode (no Vue, no DOM).

import { shortId } from "./graphData";
import type { Replay, ReplayState } from "./graphReplay";
import type { GraphGroup, GraphMessage, GraphSession } from "../types";

export interface ReplayNode extends GraphSession {
  ghost: boolean;
}

const two = (n: number): string => String(n).padStart(2, "0");

/** Epoch seconds -> the value of a `datetime-local` input (local time, minutes). */
export function toLocalInput(ts: number): string {
  const d = new Date(ts * 1000);
  return `${d.getFullYear()}-${two(d.getMonth() + 1)}-${two(d.getDate())}T${two(d.getHours())}:${two(d.getMinutes())}`;
}

/** The value of a `datetime-local` input -> epoch seconds, or null when empty or invalid. */
export function fromLocalInput(value: string): number | null {
  if (!value) return null;
  const ms = new Date(value).getTime();
  return Number.isFinite(ms) ? ms / 1000 : null;
}

/** Where `t` lies in the window, 0..1. */
export function fractionOf(replay: Replay, t: number): number {
  return replay.duration > 0 ? Math.min(1, Math.max(0, (t - replay.start) / replay.duration)) : 0;
}

/** The time at fraction `f` of the window. */
export function timeAt(replay: Replay, f: number): number {
  return replay.start + Math.min(1, Math.max(0, f)) * replay.duration;
}

/** The time of the next (dir 1) or previous (dir -1) message from `t`; the window's end or start when there is none. */
export function stepTarget(replay: Replay, t: number, dir: 1 | -1): number {
  if (dir === 1) return replay.messages.find((m) => m.ts > t)?.ts ?? replay.end;
  for (let i = replay.messages.length - 1; i >= 0; i -= 1) {
    const m = replay.messages[i]!;
    if (m.ts < t - 1e-6) return m.ts;
  }
  return replay.start;
}

/** The nodes of a replay: everyone in the window; those not on the roster now are ghosts. Sorted, so the ring is stable. */
export function replayNodes(replay: Replay, state: ReplayState, roster: GraphSession[]): ReplayNode[] {
  const known = new Map(roster.map((s) => [s.session_id, s]));
  const named = new Map<string, { handle: string; title: string }>();
  for (const m of replay.messages) {
    named.set(m.from.session_id, { handle: m.from.handle, title: m.from.title });
    if (m.to.session_id && m.to.handle) named.set(m.to.session_id, { handle: m.to.handle, title: m.to.title ?? "" });
  }
  return [...state.sessionIds]
    .sort()
    .map((id): ReplayNode => {
      const session = known.get(id);
      if (session) return { ...session, ghost: false };
      const name = named.get(id);
      return {
        session_id: id,
        handle: name?.handle || shortId(id),
        title: name?.title ?? "",
        workspace: "",
        status: "idle",
        kind: "external",
        ghost: true,
      };
    });
}

/** The groups to draw: the ones known now, and any that the messages shown so far went to. */
export function replayGroups(shown: GraphMessage[], touched: Set<string>, known: GraphGroup[]): GraphGroup[] {
  const out = known.map((g) => ({ ...g }));
  const names = new Set(known.map((g) => g.name));
  for (const name of touched) {
    if (names.has(name)) continue;
    const members = new Set<string>();
    for (const m of shown) {
      if (m.to.kind !== "group" || m.to.name !== name) continue;
      members.add(m.from.session_id);
      for (const id of m.recipients) members.add(id);
    }
    out.push({ name, members: [...members], created: 0 });
  }
  return out;
}
