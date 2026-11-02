// A conversation as the rows a chat draws: bubbles, a folded run of tool calls, and quiet notes. A run of tool calls is
// one row however long it is, because what an agent did between two sentences is not what the reader came to read.

import type { ChatItem, LiveTurn, Pending } from "../types";

export type ToolItem = Extract<ChatItem, { kind: "tool" }>;
export type SpokenItem = Exclude<ChatItem, { kind: "tool" | "note" }>;

export type Row =
  | { type: "bubble"; key: string; side: "in" | "out"; item: SpokenItem; cont: boolean; tail: boolean; pending?: Pending }
  | { type: "steps"; key: string; tools: ToolItem[] }
  | { type: "note"; key: string; text: string };

export interface Settled {
  /** The stored conversation, with the tools the turn has finished since they were stored marked as finished. */
  items: ChatItem[];
  /** The tools the running turn has called that are not stored yet. */
  tools: ToolItem[];
  /** The answer so far that is not stored yet. */
  text: string;
}

const said = (item: ChatItem): boolean => item.kind === "out" || item.kind === "user" || item.kind === "from";

/**
 * Take from a running turn what the stored conversation already holds. The session stores each step as it ends, so while
 * a turn runs its earlier tool calls and sentences are in the conversation *and* in the live turn; drawing both shows
 * every one twice. What is stored wins (it has the output), and the live turn adds only what comes after it.
 */
export function settleLive(items: readonly ChatItem[], turn: LiveTurn | undefined): Settled {
  if (!turn) return { items: [...items], tools: [], text: "" };
  let start = items.length;
  while (start > 0 && !said(items[start - 1]!)) start -= 1;
  let seen = 0;
  let text = turn.text;
  const merged = items.map((item, at): ChatItem => {
    if (at < start) return item;
    if (item.kind === "tool") {
      const live = turn.tools[seen++];
      return item.ok === undefined && live && live.ok !== null ? { ...item, ok: live.ok } : item;
    }
    if (item.kind === "in" || item.kind === "reply") {
      const needle = item.text.trim();
      const found = needle ? text.indexOf(needle) : -1;
      if (found >= 0) text = text.slice(found + needle.length);
    }
    return item;
  });
  const tools = turn.tools
    .slice(seen)
    .map((tool): ToolItem => ({ kind: "tool", name: tool.name, brief: tool.brief, ok: tool.ok ?? undefined }));
  return { items: merged, tools, text: text.trim() };
}

export function buildRows(items: readonly ChatItem[], pending: readonly Pending[], turn?: LiveTurn): Row[] {
  const rows: Row[] = [];
  const settled = settleLive(items, turn);
  let side: "in" | "out" | null = null;
  let run: ToolItem[] = [];
  let from = 0;

  const flush = (): void => {
    if (run.length) rows.push({ type: "steps", key: `s${from}`, tools: run });
    run = [];
  };

  settled.items.forEach((item, at) => {
    if (item.kind === "tool") {
      if (!run.length) from = at;
      run.push(item);
      side = null;
      return;
    }
    flush();
    if (item.kind === "note") {
      rows.push({ type: "note", key: `n${at}`, text: item.text });
      side = null;
      return;
    }
    // What the person said, from this page or typed in the session itself, or sent to it by another session, is on the right; the agent is on the left.
    const current = item.kind === "out" || item.kind === "user" || item.kind === "from" ? "out" : "in";
    rows.push({ type: "bubble", key: `m${at}`, side: current, item, cont: side === current, tail: true });
    side = current;
  });
  // The tools still running join the run they continue, so the turn is one group of steps and not two.
  if (settled.tools.length && !run.length) from = items.length;
  run.push(...settled.tools);
  flush();

  for (const entry of pending) {
    rows.push({
      type: "bubble",
      key: `p${entry.key}`,
      side: "out",
      item: {
        kind: "out",
        text: entry.text,
        // Drawn from what this page holds until the conversation has the message and the gateway can serve its pictures.
        ...(entry.pictures?.length
          ? { images: entry.pictures.map((p) => ({ id: "", media_type: p.media_type, bytes: p.bytes, src: p.src })) }
          : {}),
      },
      cont: side === "out",
      tail: true,
      pending: entry,
    });
    side = "out";
  }
  // The avatar is drawn on the last bubble of a run from the same side, as a messenger does.
  rows.forEach((row, at) => {
    const next = rows[at + 1];
    if (row.type === "bubble") row.tail = !(next?.type === "bubble" && next.side === row.side);
  });
  return rows;
}
