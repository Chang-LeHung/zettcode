// Group chats: the list the Chats pane shows (from the graph's groups), the one conversation that is open, and who is
// in each. A group's messages are read from the broker's history, newest first, and kept by the traffic events.

import { computed, reactive } from "vue";
import { gateway } from "../api/gateway";
import { ApiError } from "../api/http";
import type { GraphGroup, GraphMessage } from "../types";
import { graph, onGraphApplied } from "./graph";
import { lobby, threadOf } from "./threads";

/** A group is addressed as `#name` in the page's address, which no session id can look like. */
export const groupArg = (name: string): string => `#${name}`;
export const isGroupArg = (arg: string): boolean => arg.startsWith("#");
export const groupNameOf = (arg: string): string => (isGroupArg(arg) ? arg.slice(1) : arg);

/** A member of a group, as the member list draws it. */
export interface Member {
  id: string;
  name: string;
  online: boolean;
  status: "idle" | "working" | "offline";
  /** The person at this gateway. */
  me: boolean;
  /** The gateway lists a conversation with it, so the row can open one. */
  chat: boolean;
}

const PAGE = 50;

export const groupChat = reactive({
  name: "",
  messages: [] as GraphMessage[],
  more: false,
  loading: false,
  loadingOlder: false,
  error: "",
  sending: false,
});

/** Messages written in a group since it was last open, for the badge in the list. They are counted from the live events. */
const unread = reactive<Record<string, number>>({});

export const unreadOf = (name: string): number => unread[name] ?? 0;

const meId = (): string => lobby.status?.gateway.id ?? "";

/** One member of a group: its name from the conversation list when there is one, else from the roster, else its id. */
export function memberOf(id: string): Member {
  const thread = threadOf(id);
  const live = graph.sessions.find((session) => session.session_id === id);
  const online = live !== undefined;
  return {
    id,
    name: thread?.name ?? (live ? live.title || live.handle : "") ?? "",
    online,
    status: !online ? "offline" : live.status === "working" ? "working" : "idle",
    me: id === meId(),
    chat: thread !== undefined,
  };
}

export function membersOf(group: GraphGroup): Member[] {
  return group.members
    .map((id) => {
      const member = memberOf(id);
      return member.name ? member : { ...member, name: id.slice(0, 8) };
    })
    .sort((a, b) => Number(b.online) - Number(a.online) || a.name.localeCompare(b.name));
}

export function groupNamed(name: string): GraphGroup | undefined {
  return graph.groups.find((group) => group.name === name);
}

/** The groups, the most recently written to first; one nobody has written in yet is ordered by when it was made. */
export const groupList = computed(() =>
  [...graph.groups].sort((a, b) => (b.last?.ts ?? b.created) - (a.last?.ts ?? a.created)),
);

/** Forget the unread counts of groups the list no longer has. Runs whenever the graph is read again (see below). */
export function pruneUnread(): void {
  for (const name of Object.keys(unread)) if (!graph.groups.some((group) => group.name === name)) delete unread[name];
}

// Attached to the state change, not to a caller: the graph is read on the socket's graph event, on a reconnect, on the
// Graph page's first load and on its Retry, and every one of them replaces the groups.
onGraphApplied(pruneUnread);

/** The name a message's sender goes by in a group. */
export function senderName(message: GraphMessage): string {
  if (message.from.session_id === meId()) return "";
  return threadOf(message.from.session_id)?.name || message.from.title || message.from.handle || message.from.session_id.slice(0, 8);
}

export async function openGroup(name: string): Promise<void> {
  groupChat.name = name;
  groupChat.messages = [];
  groupChat.more = false;
  groupChat.error = "";
  groupChat.loading = true;
  unread[name] = 0;
  try {
    const page = await gateway.older(0, PAGE, name);
    if (groupChat.name !== name) return;
    groupChat.messages = page.messages;
    groupChat.more = page.more;
  } catch (error) {
    if (groupChat.name === name) groupChat.error = error instanceof ApiError ? error.message : String(error);
  } finally {
    if (groupChat.name === name) groupChat.loading = false;
  }
}

export function closeGroup(): void {
  groupChat.name = "";
  groupChat.messages = [];
}

export async function loadEarlierGroup(): Promise<void> {
  const name = groupChat.name;
  const oldest = groupChat.messages[0];
  if (!name || !oldest || !groupChat.more || groupChat.loadingOlder) return;
  groupChat.loadingOlder = true;
  try {
    const page = await gateway.older(oldest.id, PAGE, name);
    if (groupChat.name !== name) return;
    const held = new Set(groupChat.messages.map((message) => message.id));
    groupChat.messages.unshift(...page.messages.filter((message) => !held.has(message.id)));
    groupChat.more = page.more;
  } catch {
    // The button stays, and asks again.
  } finally {
    groupChat.loadingOlder = false;
  }
}

/** A message passed through the broker: when it was written in a group, show it there and count it in the list. */
export function applyGroupTraffic(message: GraphMessage): void {
  if (message.to.kind !== "group" || !message.to.name) return;
  const name = message.to.name;
  const group = groupNamed(name);
  if (group && (!group.last || group.last.id < message.id)) group.last = message;
  if (name === groupChat.name) {
    if (!groupChat.messages.some((known) => known.id === message.id)) groupChat.messages.push(message);
  } else if (group && message.from.session_id !== meId()) {
    // Only for a group the list shows: a badge on a row that does not exist (yet) has nothing to open.
    unread[name] = (unread[name] ?? 0) + 1;
  }
}

/** Write to the open group as the person at the gateway. Returns what went wrong, or an empty string. */
export async function sendToGroup(name: string, text: string): Promise<string> {
  groupChat.sending = true;
  try {
    await gateway.sendGroup(name, text);
    return "";
  } catch (error) {
    return error instanceof ApiError ? error.message : String(error);
  } finally {
    groupChat.sending = false;
  }
}
