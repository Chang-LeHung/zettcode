// The turns that are running now, as the answers and tool calls come in. What is kept here is a view: when a turn ends it
// is dropped, and the stored conversation (which the gateway has read by then) shows what it came to.

import { reactive } from "vue";
import type { LiveTurn, StreamPiece } from "../types";

/** The running turn of each session that has one, by session id. */
export const streams = reactive<Record<string, LiveTurn>>({});

const empty = (): LiveTurn => ({ text: "", thinking: false, tools: [] });

/** How many pieces (an end included) have been heard per session: a read compares it before and after it was asked. */
const heard = new Map<string, number>();

/** Note what has been heard so far, to give `seedStream` when the read that follows answers. */
export function streamMark(id: string): number {
  return heard.get(id) ?? 0;
}

export function applyStream(id: string, piece: StreamPiece): void {
  heard.set(id, streamMark(id) + 1);
  if (piece.kind === "end") {
    delete streams[id];
    return;
  }
  const turn = piece.kind === "begin" ? (streams[id] = empty()) : (streams[id] ??= empty());
  if (piece.kind === "text") {
    turn.thinking = false;
    turn.text += piece.text;
  } else if (piece.kind === "thinking") {
    turn.thinking = true;
  } else if (piece.kind === "tool") {
    turn.thinking = false;
    turn.tools.push({ id: piece.id, name: piece.name, brief: piece.brief, ok: null });
  } else if (piece.kind === "tool_end") {
    const tool = turn.tools.find((one) => one.id === piece.id);
    if (tool) tool.ok = piece.ok;
  }
}

/**
 * Take the turn a freshly read conversation says is running, unless pieces of it have already arrived: they are newer.
 * `mark` is `streamMark` from before the read was asked: when anything was heard since, the read is older than the
 * socket, and its turn may be one whose end was heard meanwhile — seeding it would bring back a turn nothing ends.
 */
export function seedStream(id: string, turn: LiveTurn | null, mark?: number): void {
  if (mark !== undefined && mark !== streamMark(id)) return;
  if (turn && !(id in streams)) streams[id] = turn;
}

/** Forget every turn: pieces were missed while the socket was away, and the next read says what is running. */
export function resetStreams(): void {
  for (const id of Object.keys(streams)) delete streams[id];
}
