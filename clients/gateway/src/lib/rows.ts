// A conversation as the rows a chat draws: bubbles, a folded run of tool calls, and quiet notes. A run of tool calls is
// one row however long it is, because what an agent did between two sentences is not what the reader came to read.

import type { ChatItem, Pending } from "../types";

export type ToolItem = Extract<ChatItem, { kind: "tool" }>;
export type SpokenItem = Exclude<ChatItem, { kind: "tool" | "note" }>;

export type Row =
  | { type: "bubble"; key: string; side: "in" | "out"; item: SpokenItem; cont: boolean; tail: boolean; pending?: Pending }
  | { type: "steps"; key: string; tools: ToolItem[] }
  | { type: "note"; key: string; text: string };

export function buildRows(items: readonly ChatItem[], pending: readonly Pending[]): Row[] {
  const rows: Row[] = [];
  let side: "in" | "out" | null = null;
  let run: ToolItem[] = [];

  const flush = (at: number): void => {
    if (run.length) rows.push({ type: "steps", key: `s${at}`, tools: run });
    run = [];
  };

  items.forEach((item, at) => {
    if (item.kind === "tool") {
      run.push(item);
      side = null;
      return;
    }
    flush(at);
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
  flush(items.length);

  for (const entry of pending) {
    rows.push({
      type: "bubble",
      key: `p${entry.key}`,
      side: "out",
      item: { kind: "out", text: entry.text },
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
