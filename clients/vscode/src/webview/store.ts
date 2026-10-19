/** The webview's one place for what it knows: the host's state, the transcript, and what the reader has open. */

import { reactive } from "vue";

import type { Mention } from "../../../typescript/src/types.js";
import type { DiffRow } from "../core/diff.js";
import type { ChangeSummary } from "../core/ledger.js";
import type { AttachedImage, HostMessage, WebviewMessage, WebviewState } from "../core/protocol.js";
import { COMPACT_TURN, createTurn, isAnnouncement, type CompactionBlock, type Turn } from "../core/state.js";

declare function acquireVsCodeApi(): { postMessage(message: unknown): void };

const host = acquireVsCodeApi();

/** Send a message to the extension host. */
export function post(message: WebviewMessage): void {
  if (message.type === "compact" && !beginCompaction()) {
    return;
  }
  host.postMessage(message);
}

export type Overlay = "drawer" | "context" | "models" | "effort" | "permission" | "add-model" | null;
export type ToastLevel = "info" | "warn" | "error";

export interface QueuedMessage {
  id: number;
  text: string;
  images: AttachedImage[];
}

export interface Toast {
  id: number;
  text: string;
  level: ToastLevel;
}

export interface DiffPayload {
  rows: DiffRow[];
  truncated: boolean;
}

/** The most images one message carries. */
export const MAX_IMAGES = 4;

export const state = reactive({
  ui: null as WebviewState | null,
  turns: [] as Turn[],
  draft: "",
  attachments: [] as AttachedImage[],
  queue: [] as QueuedMessage[],
  toasts: [] as Toast[],
  changes: {} as Record<string, ChangeSummary[]>,
  diffs: {} as Record<string, DiffPayload>,
  mentions: null as { query: string; items: Mention[] } | null,
  collapsed: new Set<string>(),
  openTools: new Set<string>(),
  /** Commands open their card by default; the ones the reader folded. */
  closedTools: new Set<string>(),
  openReasoning: new Set<string>(),
  /** Compaction summaries and receipts the reader opened. */
  openNotes: new Set<string>(),
  openFiles: new Set<string>(),
  overlay: null as Overlay,
  sessionsLoading: false,
  renaming: false,
  dragging: false,
  /** How many older requests the host has not sent yet; a reloaded conversation shows its latest ones first. */
  earlier: 0,
  /** The row a compaction in progress is drawn in, until the host says how it ended. */
  compacting: null as string | null,
  /** The request whose message was just jumped to from the rail, so it can flash once. */
  flashed: null as string | null,
  /** Bumped to move the cursor into the message box. */
  focus: 0,
  /** The search over the conversation (Ctrl/Cmd+F): whether its bar is open, what it looks for and where it stands. */
  find: { open: false, query: "", index: 0, count: 0, focus: 0 },
  /** Bumped whenever the transcript grew, so the view can follow it to the bottom. */
  tick: 0,
});

let nextId = 0;
const toastTimers = new Map<number, number>();

export function toast(text: string, level: ToastLevel = "info"): void {
  // The same message again is the same message: it stays one toast, and its time starts over.
  const existing = state.toasts.find((candidate) => candidate.text === text && candidate.level === level);
  const item: Toast = existing ?? { id: (nextId += 1), text, level };
  if (existing === undefined) {
    state.toasts.push(item);
  } else {
    window.clearTimeout(toastTimers.get(item.id));
  }
  while (state.toasts.length > 4) {
    state.toasts.shift();
  }
  toastTimers.set(
    item.id,
    window.setTimeout(
      () => {
        toastTimers.delete(item.id);
        const index = state.toasts.findIndex((candidate) => candidate.id === item.id);
        if (index >= 0) {
          state.toasts.splice(index, 1);
        }
      },
      level === "error" ? 7000 : 4000,
    ),
  );
}

export function openOverlay(overlay: Overlay): void {
  state.overlay = overlay;
  if (overlay === "drawer") {
    if (!state.sessionsLoading) {
      state.sessionsLoading = true;
      post({ type: "refresh-sessions" });
    }
  } else if (overlay === "context") {
    post({ type: "context" });
  }
}

export function closeOverlay(): void {
  state.overlay = null;
}

/** Open the search bar and put the cursor in it; a short selection in the view becomes the query. */
export function openFind(selection = ""): void {
  const text = selection.trim();
  if (text && text.length <= 100 && !text.includes("\n")) {
    state.find.query = text;
  }
  state.find.open = true;
  state.find.focus += 1;
}

export function closeFind(): void {
  state.find.open = false;
  state.find.count = 0;
  state.focus += 1;
}

export function toggleTurn(id: string): void {
  if (state.collapsed.has(id)) {
    state.collapsed.delete(id);
  } else {
    state.collapsed.add(id);
  }
}

/** Fold every request, or open them all again when all are folded already. */
export function toggleAllTurns(): void {
  const ids = state.turns.filter((turn) => !turn.aside).map((turn) => turn.id);
  const allFolded = ids.length > 0 && ids.every((id) => state.collapsed.has(id));
  state.collapsed.clear();
  if (!allFolded) {
    ids.forEach((id) => state.collapsed.add(id));
  }
}

/** Make a request's message flash once, so the eye finds where a jump landed. */
let flashTimer: number | undefined;
export function flash(id: string): void {
  window.clearTimeout(flashTimer);
  state.flashed = null;
  // A frame later, so jumping to the same message twice replays the animation.
  window.requestAnimationFrame(() => {
    state.flashed = id;
    flashTimer = window.setTimeout(() => {
      state.flashed = null;
    }, 1400);
  });
}

export function toggleIn(set: Set<string>, key: string): void {
  if (set.has(key)) {
    set.delete(key);
  } else {
    set.add(key);
  }
}

// -- compaction -----------------------------------------------------------------

export { COMPACT_TURN };

/** The longest a compaction row spins without word from the host before it gives up. */
const COMPACT_PATIENCE_MS = 5 * 60_000;
let compactTimer: number | undefined;

/**
 * Compacting can take a while and the host answers once, when it is done. So the row is drawn here the moment the
 * request goes out: a spinner now, and the host's one reply becomes its ending. A success only says it was compacted;
 * the summary itself is not shown, and a refusal or a failure says why.
 */
function beginCompaction(): boolean {
  if (state.ui?.busy === true) {
    toast("Stop the run before compacting.", "warn");
    return false;
  }
  if (state.compacting !== null) {
    return false;
  }
  const turn = createTurn("/compact", [], Date.now(), `${COMPACT_TURN}${Date.now().toString(36)}`);
  turn.aside = true;
  turn.blocks.push({ kind: "compaction", running: true, applied: false, summary: null });
  state.turns.push(turn);
  state.compacting = turn.id;
  state.tick += 1;
  window.clearTimeout(compactTimer);
  compactTimer = window.setTimeout(() => endCompaction("The server did not answer.", true), COMPACT_PATIENCE_MS);
  return true;
}

function endCompaction(text: string, failed: boolean, summary?: string): void {
  window.clearTimeout(compactTimer);
  const turn = state.turns.find((candidate) => candidate.id === state.compacting);
  state.compacting = null;
  if (turn === undefined) {
    toast(text, failed ? "warn" : "info");
    return;
  }
  const block = turn.blocks.find((candidate): candidate is CompactionBlock => candidate.kind === "compaction");
  if (block !== undefined) {
    block.running = false;
    block.applied = !failed && /^Compacted /.test(text);
    if (block.applied && summary) {
      block.summary = summary;
    }
  }
  if (failed) {
    turn.blocks.push({ kind: "notice", text });
    turn.status = "failed";
  } else {
    turn.status = "done";
  }
  turn.finishedAt = Date.now();
  state.tick += 1;
}

// -- follow-ups ------------------------------------------------------------

/** Hold a message typed while a request runs; it goes when the run ends, or right now when you steer it in. */
export function enqueue(text: string, images: AttachedImage[]): void {
  state.queue.push({ id: (nextId += 1), text, images });
}

export function removeQueued(id: number): void {
  const index = state.queue.findIndex((item) => item.id === id);
  if (index >= 0) {
    state.queue.splice(index, 1);
  }
}

/** Steer a queued message into the running request, or send it now when nothing is running. */
export function sendQueued(id: number): void {
  const item = state.queue.find((candidate) => candidate.id === id);
  if (item === undefined) {
    return;
  }
  removeQueued(id);
  if (state.ui?.busy === true) {
    post({ type: "steer", text: item.text });
    return;
  }
  post({
    type: "prompt",
    text: item.text,
    images: item.images.map((image) => ({ data: image.data, mediaType: image.mediaType })),
  });
  state.tick += 1;
}

/** The run ended: the next follow-up goes, unless the run was stopped or failed, when they wait for a hand. */
function drainQueue(): void {
  const first = state.queue[0];
  if (first === undefined || state.ui === null || state.ui.busy) {
    return;
  }
  // A line announcing a change is not a request: it must not hide how the last request ended.
  const last = state.turns.filter((turn) => !isAnnouncement(turn)).pop();
  if (last !== undefined && last.status !== "done") {
    return;
  }
  sendQueued(first.id);
}

// -- messages from the host --------------------------------------------------

function appendDelta(turn: Turn, kind: "text" | "reasoning", text: string): void {
  const last = turn.blocks[turn.blocks.length - 1];
  if (last?.kind === kind) {
    last.text += text;
    return;
  }
  turn.blocks.push(kind === "text" ? { kind: "text", text } : { kind: "reasoning", text });
}

export function handleHost(message: HostMessage): void {
  switch (message.type) {
    case "init":
      state.ui = message.state;
      state.turns = message.turns;
      state.compacting = null;
      state.tick += 1;
      break;
    case "state": {
      const wasBusy = state.ui?.busy === true;
      state.ui = message.state;
      if (wasBusy && !message.state.busy) {
        drainQueue();
      }
      break;
    }
    case "turn": {
      const index = state.turns.findIndex((turn) => turn.id === message.turn.id);
      if (index === -1) {
        state.turns.push(message.turn);
      } else {
        state.turns[index] = message.turn;
      }
      state.tick += 1;
      break;
    }
    case "turn-delta": {
      const turn = state.turns.find((candidate) => candidate.id === message.turnId);
      if (turn === undefined) {
        break;
      }
      if (message.text) {
        appendDelta(turn, "text", message.text);
      }
      if (message.reasoning) {
        appendDelta(turn, "reasoning", message.reasoning);
      }
      state.tick += 1;
      break;
    }
    case "turns":
      state.turns = message.turns;
      state.earlier = message.earlier ?? 0;
      state.openTools.clear();
      state.closedTools.clear();
      state.openReasoning.clear();
      state.openNotes.clear();
      state.collapsed.clear();
      state.compacting = null;
      window.clearTimeout(compactTimer);
      state.tick += 1;
      break;
    case "earlier": {
      // Older requests go in front of the ones on show; a request already shown is not added twice.
      const have = new Set(state.turns.map((turn) => turn.id));
      state.turns = [...message.turns.filter((turn) => !have.has(turn.id)), ...state.turns];
      state.earlier = message.earlier;
      break;
    }
    case "sessions":
      if (state.ui !== null) {
        state.ui.sessions = message.sessions;
      }
      state.sessionsLoading = false;
      break;
    case "mentions":
      state.mentions = { query: message.query, items: message.items };
      break;
    case "images":
      state.attachments = [...state.attachments, ...message.images].slice(0, MAX_IMAGES);
      break;
    case "notice":
      // While a compaction is out, the host's next notice is its answer, and it belongs in the row, not a toast.
      if (state.compacting !== null) {
        endCompaction(message.text, message.level !== "info", message.summary);
      } else {
        toast(message.text, message.level);
      }
      break;
    case "find":
      openFind(window.getSelection()?.toString() ?? "");
      break;
    case "history":
      state.overlay = message.open ? "drawer" : state.overlay === "drawer" ? null : state.overlay;
      if (message.open && !state.sessionsLoading) {
        state.sessionsLoading = true;
        post({ type: "refresh-sessions" });
      }
      break;
    case "model-form":
      if (message.open) {
        state.overlay = "add-model";
      } else if (state.overlay === "add-model") {
        state.overlay = null;
      }
      break;
    case "changes":
      state.changes[message.turnId] = message.files;
      break;
    case "diff-rows":
      state.diffs[`${message.turnId}::${message.path}`] = { rows: message.rows, truncated: message.truncated };
      break;
  }
}
