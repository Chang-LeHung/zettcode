// The list of threads, and the state of the gateway beside it.

import { computed, reactive } from "vue";
import { gateway } from "../api/gateway";
import { unreadChats } from "../lib/unread";
import type { GatewayStatus, Thread } from "../types";

export const lobby = reactive({
  threads: [] as Thread[],
  status: null as GatewayStatus | null,
  /** Whether the event socket is open: when it is not, what is shown may be out of date. */
  live: false,
  loaded: false,
});

export const byId = computed(() => new Map(lobby.threads.map((thread) => [thread.id, thread])));

export const totalUnread = computed(() => lobby.threads.reduce((sum, thread) => sum + thread.unread, 0));
/** How many conversations have something unread: what the tab shows. */
export const chatsWithUnread = computed(() => unreadChats(lobby.threads));

export const daemons = computed(() => lobby.threads.filter((thread) => thread.kind === "daemon"));

export function applyThreads(threads: Thread[], status?: GatewayStatus): void {
  lobby.threads = threads;
  if (status) lobby.status = status;
  lobby.loaded = true;
}

export async function loadThreads(): Promise<void> {
  const data = await gateway.threads();
  applyThreads(data.threads, data.status);
}

export function threadOf(id: string): Thread | undefined {
  return byId.value.get(id);
}

/** What a thread is doing, in the words of its subtitle. */
export function isBusy(thread: Thread): boolean {
  return thread.status === "working" || thread.status === "starting";
}

/** Whether a message can be written to a thread now. */
export function canWrite(thread: Thread): boolean {
  return thread.online && lobby.status?.broker.reachable !== false;
}
