// The conversation that is open: what the session has said, what this page has sent that the session has not stored
// yet, and the drafts of every thread. The words themselves are the session's stored conversation; this page only
// asks for them again when the gateway says they moved.

import { reactive } from "vue";
import { gateway } from "../api/gateway";
import { ApiError } from "../api/http";
import { t } from "../i18n";
import { pend, settle } from "../lib/pending";
import { debounce, storage } from "../lib/storage";
import { seenNow } from "../lib/unread";
import type { ChatItem, Pending, Picture, Thread } from "../types";
import { prefs } from "./prefs";
import { seedStream } from "./stream";
import { lobby, threadOf } from "./threads";

export const chat = reactive({
  id: "",
  thread: null as Thread | null,
  items: [] as ChatItem[],
  total: 0,
  truncated: false,
  /** Where the unread stretch begins in `items`, or null when there is none: the line an opened chat scrolls to, kept
      for the visit so that reading clears the badge without moving it. */
  unreadFrom: null as number | null,
  loading: false,
  /** The whole conversation is being read, after "Show earlier messages". */
  loadingEarlier: false,
  error: "",
  pending: [] as Pending[],
  /** Bumped when the conversation grew, so a view can decide whether to follow it. */
  revision: 0,
  /** The reader is at the bottom of the open conversation, so what arrives is seen as it arrives. */
  atBottom: true,
});

const waiting = new Map<string, Pending[]>();
let sequence = 0;
let generation = 0;
/** Whether the whole conversation was asked for, so that a refresh does not go back to its end. */
let showAll = false;
/**
 * Whether this visit has not yet read where the unread stretch began. One flag for the visit rather than "is a load in
 * flight": a `thread` event arriving before the opening read answers starts a second read, and both would otherwise
 * count as opening reads — the newer one would place the line above a message that arrived after the chat was opened.
 */
let readingLine = true;

function pendingFor(id: string): Pending[] {
  let list = waiting.get(id);
  if (!list) {
    list = reactive([]) as Pending[];
    waiting.set(id, list);
  }
  return list;
}

async function load(id: string, all: boolean): Promise<void> {
  const mine = ++generation;
  if (all) showAll = true;
  // The first read of this visit: what was unread when the chat was opened, which is where it stops. The flag is used
  // up here, before the answer is awaited: a `thread` event arriving meanwhile starts a second read, and that one must
  // neither place the line nor move it to a message that arrived after the chat was opened.
  const opening = readingLine;
  if (opening) readingLine = false;
  try {
    const detail = await gateway.thread(id, showAll);
    if (mine !== generation || chat.id !== id) return;
    const grew = detail.items.length !== chat.items.length;
    const before = chat.items.length;
    chat.thread = detail.thread;
    seedStream(id, detail.live);
    chat.items = detail.items;
    chat.total = detail.total;
    chat.truncated = detail.truncated;
    // The line is where this visit found the unread stretch and stays there while the chat is open: what arrives later
    // is counted by the button at the bottom, not folded into the place the reader left off. "Show earlier messages"
    // prepends, so every index it holds moves with it.
    if (opening) chat.unreadFrom = detail.unread_from ?? null;
    else if (chat.unreadFrom !== null && all && detail.items.length > before)
      chat.unreadFrom += detail.items.length - before;
    chat.error = "";
    const list = pendingFor(id);
    const left = settle(list, detail.items);
    const settled = left.length !== list.length;
    if (settled) list.splice(0, list.length, ...left);
    if (grew || settled) chat.revision += 1;
  } catch (error) {
    // Nothing was read, so the next attempt is still the first one and may place the line after all.
    if (opening) readingLine = true;
    if (mine !== generation || chat.id !== id) return;
    chat.error = error instanceof ApiError ? error.message : String(error);
  } finally {
    if (mine === generation) chat.loading = false;
  }
}

/** Open a thread's conversation. */
export async function openChat(id: string): Promise<void> {
  if (chat.id !== id) {
    showAll = false;
    chat.id = id;
    chat.thread = threadOf(id) ?? null;
    chat.items = [];
    chat.total = 0;
    chat.truncated = false;
    chat.unreadFrom = null;
    readingLine = true;
    chat.error = "";
    chat.pending = pendingFor(id);
    chat.loading = true;
  }
  await load(id, false);
  chat.revision += 1;
}

export function closeChat(): void {
  generation += 1;
  chat.id = "";
  chat.thread = null;
  chat.items = [];
  chat.unreadFrom = null;
  readingLine = true;
  chat.pending = [];
}

/** Read the conversation again because the gateway said it moved. */
export async function refreshChat(id: string): Promise<void> {
  if (chat.id === id) await load(id, false);
}

export async function loadEarlier(): Promise<void> {
  if (!chat.id || chat.loadingEarlier) return;
  chat.loadingEarlier = true;
  try {
    await load(chat.id, true);
  } finally {
    chat.loadingEarlier = false;
  }
}

// ---- sending
export async function sendMessage(text: string, reply: boolean, pictures: readonly Picture[] = []): Promise<void> {
  const id = chat.id;
  if (!id) return;
  const list = pendingFor(id);
  list.push(pend(++sequence, text, chat.items, list, Date.now(), pictures));
  const entry = list[list.length - 1]!;
  chat.revision += 1;
  await deliver(id, entry, reply);
}

async function deliver(id: string, entry: Pending, reply: boolean): Promise<void> {
  entry.state = "sending";
  delete entry.error;
  try {
    const sent = await gateway.send(id, entry.text, reply, entry.pictures);
    // A steered reply also runs a turn (a session that chose to steer answered it); the page itself always sends
    // follow-ups, so that word only reaches a page from a server newer than it.
    entry.state = sent.disposition === "queued" ? "queued" : "started";
    lobby.status = sent.status;
  } catch (error) {
    entry.state = "failed";
    const failure = error instanceof ApiError ? error : new ApiError(0, { message: String(error) });
    entry.error = { code: failure.code, message: failure.message, uncertain: failure.body.uncertain === true };
  }
  if (chat.id === id) chat.revision += 1;
}

/** Send a failed message again. Only the person asks for this: a message that may have arrived is never resent by itself. */
export async function retry(entry: Pending, reply: boolean): Promise<void> {
  const id = chat.id;
  if (!id) return;
  const list = pendingFor(id);
  const at = list.indexOf(entry);
  if (at < 0) return;
  list.splice(at, 1);
  await sendMessage(entry.text, reply, entry.pictures ?? []);
}

export function dismiss(entry: Pending): void {
  const list = pendingFor(chat.id);
  const at = list.indexOf(entry);
  if (at >= 0) list.splice(at, 1);
}

// ---- read marks
const mark = debounce((id: string) => {
  gateway.read(id).catch(() => {});
}, 350);

/** Say that what the open thread has said has been seen. */
export function markRead(): void {
  const thread = chat.id ? threadOf(chat.id) : undefined;
  // Nothing is seen before the conversation is here: a chat that was just opened would otherwise be marked read
  // before the reader saw what the line points at, and the page would land at the bottom instead of on it. This holds
  // because a refresh is asked for from a watcher, which runs after `load` cleared the flag: a `flush: "sync"` watcher
  // would mark a chat read that is still being read and leave the badge up.
  if (!thread || chat.loading || !chat.items.length) return;
  // As in any messenger, what is above the reader's place has not been seen: it stays unread until they come down to it.
  if (!seenNow({ hidden: document.hidden, atBottom: chat.atBottom, unread: thread.unread })) return;
  thread.unread = 0;
  mark(thread.id);
}

// ---- drafts
const drafts = reactive<Record<string, string>>({});

export function draftOf(id: string): string {
  if (!(id in drafts)) drafts[id] = storage.get(`draft.${id}`, "");
  return drafts[id] ?? "";
}

export function setDraft(id: string, text: string): void {
  drafts[id] = text;
  if (text) storage.set(`draft.${id}`, text);
  else storage.remove(`draft.${id}`);
}

// ---- asking for an answer
const replies = reactive<Record<string, boolean>>({});

/** Whether a message to this thread asks the agent to answer with `send_message`: on for a daemon unless switched off. */
export function wantsReply(thread: Thread): boolean {
  return replies[thread.id] ?? (thread.kind === "daemon" && prefs.askReply);
}

export function setWantsReply(id: string, value: boolean): void {
  replies[id] = value;
}
