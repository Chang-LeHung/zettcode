/** Parse `text/event-stream` into frames, with no dependency and no assumption about chunk boundaries. */

import type { StreamFrame } from "./types.js";

/** One parsed frame before its payload is typed. */
interface RawFrame {
  event: string;
  data: string;
}

/**
 * Read a response body as server-sent events.
 *
 * A frame may be split across any number of chunks, and several may arrive in one; the parser buffers until a blank
 * line, joins the `data:` lines of a frame, and ignores comments (`:` lines) and fields it does not use. The
 * terminal `\r\n` form is accepted as well as `\n`.
 */
export async function* sseFrames(
  body: ReadableStream<Uint8Array>,
  signal?: AbortSignal,
): AsyncGenerator<StreamFrame> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      if (signal?.aborted) {
        throw signal.reason ?? new Error("The request was aborted");
      }
      const { value, done } = await reader.read();
      if (done) {
        break;
      }
      buffer += decoder.decode(value, { stream: true }).replaceAll("\r\n", "\n");
      let boundary = buffer.indexOf("\n\n");
      while (boundary >= 0) {
        const block = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const frame = parseBlock(block);
        if (frame) {
          yield asStreamFrame(frame);
        }
        boundary = buffer.indexOf("\n\n");
      }
    }
    buffer += decoder.decode();
    if (buffer.trim()) {
      const frame = parseBlock(buffer);
      if (frame) {
        yield asStreamFrame(frame);
      }
    }
  } finally {
    reader.releaseLock();
  }
}

/** Parse one block of an event stream; `null` when it carries no data. */
export function parseBlock(block: string): RawFrame | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (!line || line.startsWith(":")) {
      continue;
    }
    const colon = line.indexOf(":");
    const field = colon < 0 ? line : line.slice(0, colon);
    let value = colon < 0 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) {
      value = value.slice(1);
    }
    if (field === "event") {
      event = value;
    } else if (field === "data") {
      data.push(value);
    }
  }
  if (data.length === 0) {
    return null;
  }
  return { event, data: data.join("\n") };
}

/** Type a raw frame: the payload is JSON when it can be, and the text when it cannot. */
export function asStreamFrame(frame: RawFrame): StreamFrame {
  let data: unknown = frame.data;
  try {
    data = JSON.parse(frame.data);
  } catch {
    // An unparseable payload is kept as text rather than thrown away.
  }
  const event = (["event", "result", "error", "cancelled"].includes(frame.event) ? frame.event : "event") as
    | "event"
    | "result"
    | "error"
    | "cancelled";
  return { event, data: data as StreamFrame["data"] };
}
