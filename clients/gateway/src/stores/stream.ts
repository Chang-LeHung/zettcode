// The turns that are running now, as the answers and tool calls come in. What is kept here is a view: when a turn ends it
// is dropped, and the stored conversation (which the gateway has read by then) shows what it came to.

import { reactive } from "vue";
import type { LiveTurn, StreamPiece } from "../types";

/** The running turn of each session that has one, by session id. */
export const streams = reactive<Record<string, LiveTurn>>({});

const empty = (): LiveTurn => ({ text: "", thinking: false, tools: [] });

export function applyStream(id: string, piece: StreamPiece): void {
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

/** Take the turn a freshly read conversation says is running, unless pieces of it have already arrived: they are newer. */
export function seedStream(id: string, turn: LiveTurn | null): void {
  if (turn && !(id in streams)) streams[id] = turn;
}

/** Forget every turn: pieces were missed while the socket was away, and the next read says what is running. */
export function resetStreams(): void {
  for (const id of Object.keys(streams)) delete streams[id];
}
