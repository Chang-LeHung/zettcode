// The turns that are running now, as the answers and tool calls come in. What is kept here is a view: when a turn ends it
// is dropped, and the stored conversation (which the gateway has read by then) shows what it came to.
//
// A turn can reach this page two ways: as pieces on the socket, and as a snapshot inside a read of the conversation. The
// two are not ordered by the network, so the gateway numbers each turn and the number rides on both: a turn whose end
// was heard is never brought back by a snapshot that was asked before it ended, and an end only removes the turn it names.

import { reactive } from "vue";
import type { LiveTurn, StreamPiece } from "../types";

/** The running turn of each session that has one, by session id. */
export const streams = reactive<Record<string, LiveTurn>>({});

const empty = (turn: number | undefined): LiveTurn =>
  turn === undefined ? { text: "", thinking: false, tools: [] } : { turn, text: "", thinking: false, tools: [] };

/** The newest turn of each session whose end was heard. The gateway numbers turns upward, so anything at or below is over. */
const ended = new Map<string, number>();

/** How many pieces have been heard per session: the guard for a gateway that does not number its turns. */
const heard = new Map<string, number>();

/** Note what has been heard so far, to give `seedStream` when the read that follows answers. */
export function streamMark(id: string): number {
  return heard.get(id) ?? 0;
}

export function applyStream(id: string, piece: StreamPiece): void {
  heard.set(id, streamMark(id) + 1);
  const number = piece.turn;
  // A late piece of a turn that has already ended must not start it again.
  if (number !== undefined && number <= (ended.get(id) ?? 0)) return;
  const current = streams[id];
  if (piece.kind === "end") {
    if (number !== undefined) ended.set(id, number);
    // The end of an older turn leaves a newer one running.
    if (number === undefined || current?.turn === undefined || current.turn <= number) delete streams[id];
    return;
  }
  const newer = number !== undefined && current?.turn !== undefined && number > current.turn;
  const turn = piece.kind === "begin" || !current || newer ? (streams[id] = empty(number)) : current;
  if (turn.turn === undefined && number !== undefined) turn.turn = number;
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
 *
 * A numbered turn is refused when its end was already heard: the read was answered after the turn ended, from before. A
 * gateway that does not number its turns is held to `mark`, the `streamMark` taken before the read was asked: when anything
 * was heard since, the read is older than the socket.
 */
export function seedStream(id: string, turn: LiveTurn | null, mark?: number): void {
  if (!turn || id in streams) return;
  if (turn.turn !== undefined) {
    if (turn.turn <= (ended.get(id) ?? 0)) return;
  } else if (mark !== undefined && mark !== streamMark(id)) {
    return;
  }
  streams[id] = turn;
}

/** Forget every turn: pieces were missed while the socket was away, and the next read says what is running. */
export function resetStreams(): void {
  for (const id of Object.keys(streams)) delete streams[id];
  // A gateway that restarted counts its turns from the start again, so what was over before is not over now.
  ended.clear();
}
