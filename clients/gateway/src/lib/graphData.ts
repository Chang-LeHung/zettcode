// What the Graph page knows about the sessions, worked out from the broker's answer: which nodes there are, how a new
// message changes the totals, and what to say about a node, a pair or a group.

import { pairKey, preview } from "./graph";
import type { GraphData, GraphEdge, GraphGroup, GraphMessage, GraphSession } from "../types";

/** How many messages the page keeps; the broker sends the same number. */
export const RECENT_LIMIT = 50;

/** A node on the ring: a session, or one that is gone and still shows in the latest traffic. */
export interface GraphNode extends GraphSession {
  ghost: boolean;
}

export function emptyGraph(): GraphData {
  return { sessions: [], groups: [], edges: [], recent: [] };
}

export function shortId(id: string): string {
  return id.length > 8 ? id.slice(0, 8) : id;
}

/** The session ids a message reached; a one-to-one message that names its target but lists nobody reached nobody. */
export function reached(message: GraphMessage): string[] {
  return message.recipients.filter((id) => id !== message.from.session_id);
}

/** The nodes: the roster, then the sessions that are gone and appear in the latest traffic, dim. */
export function deriveNodes(data: GraphData): GraphNode[] {
  const nodes = new Map<string, GraphNode>();
  for (const session of data.sessions) nodes.set(session.session_id, { ...session, ghost: false });
  const ghost = (id: string, handle: string, title: string): void => {
    if (!id || nodes.has(id)) return;
    nodes.set(id, {
      session_id: id,
      handle: handle || shortId(id),
      title,
      workspace: "",
      status: "idle",
      kind: "external",
      ghost: true,
    });
  };
  for (const message of data.recent) {
    ghost(message.from.session_id, message.from.handle, message.from.title);
    for (const id of message.recipients) {
      ghost(id, id === message.to.session_id ? (message.to.handle ?? "") : "", id === message.to.session_id ? (message.to.title ?? "") : "");
    }
  }
  return [...nodes.values()];
}

/** Count a message into the totals and the feed. False when the feed already holds it. */
export function applyTrafficTo(data: GraphData, message: GraphMessage): boolean {
  if (data.recent.some((known) => known.id === message.id)) return false;
  data.recent.push(message);
  if (data.recent.length > RECENT_LIMIT) data.recent.splice(0, data.recent.length - RECENT_LIMIT);
  // Only one-to-one messages are pair totals; a group's message is not.
  const target = message.to.kind === "session" ? reached(message)[0] : undefined;
  if (target) {
    const key = pairKey(message.from.session_id, target);
    const edge = data.edges.find((candidate) => pairKey(candidate.a, candidate.b) === key);
    if (edge) {
      edge.count += 1;
      edge.last = Math.max(edge.last, message.ts);
    } else {
      data.edges.push({ a: message.from.session_id, b: target, count: 1, last: message.ts });
    }
  }
  return true;
}

export interface NodeStats {
  sent: number;
  received: number;
  /** Every one-to-one message the node has taken part in, from the pair totals. */
  exchanged: number;
  groups: string[];
  last: GraphMessage | null;
}

export function statsOf(data: GraphData, id: string): NodeStats {
  let sent = 0;
  let received = 0;
  let last: GraphMessage | null = null;
  for (const message of data.recent) {
    const mine = message.from.session_id === id;
    const got = message.recipients.includes(id);
    if (mine) sent += 1;
    if (got) received += 1;
    if (mine || got) last = message;
  }
  const exchanged = data.edges.reduce((sum, edge) => sum + (edge.a === id || edge.b === id ? edge.count : 0), 0);
  const groups = data.groups.filter((group) => group.members.includes(id)).map((group) => group.name);
  return { sent, received, exchanged, groups, last };
}

/** The latest `limit` messages between two sessions, newest first. */
export function pairMessages(data: GraphData, a: string, b: string, limit = 3): GraphMessage[] {
  const out: GraphMessage[] = [];
  for (let i = data.recent.length - 1; i >= 0 && out.length < limit; i -= 1) {
    const message = data.recent[i]!;
    if (message.to.kind !== "session") continue;
    const from = message.from.session_id;
    const to = reached(message)[0] ?? message.to.session_id;
    if ((from === a && to === b) || (from === b && to === a)) out.push(message);
  }
  return out;
}

/** Everything the page shows as a count: the sessions, the groups and every message the totals know of. */
export function totals(data: GraphData): { sessions: number; groups: number; messages: number } {
  const pairs = data.edges.reduce((sum, edge) => sum + edge.count, 0);
  const grouped = data.recent.filter((message) => message.to.kind === "group").length;
  return { sessions: data.sessions.length, groups: data.groups.length, messages: pairs + grouped };
}

/** The group a message went to, or the handle of the session. */
export function targetLabel(message: GraphMessage): string {
  if (message.to.kind === "group") return `#${message.to.name ?? ""}`;
  return message.to.handle || message.to.title || shortId(message.to.session_id ?? "");
}

export function senderLabel(message: GraphMessage): string {
  return message.from.handle || message.from.title || shortId(message.from.session_id);
}

export function messagePreview(message: GraphMessage, max = 90): string {
  return preview(message.text, max);
}

/** The most text a tooltip shows of one message. */
export const TIP_TEXT_LIMIT = 600;

export function tipText(message: GraphMessage): string {
  const flat = message.text.trim();
  return flat.length > TIP_TEXT_LIMIT ? `${flat.slice(0, TIP_TEXT_LIMIT)}…` : flat;
}

export function groupByName(data: GraphData, name: string): GraphGroup | undefined {
  return data.groups.find((group) => group.name === name);
}

export function edgeOf(data: GraphData, a: string, b: string): GraphEdge | undefined {
  const key = pairKey(a, b);
  return data.edges.find((edge) => pairKey(edge.a, edge.b) === key);
}

/** The ids that count as the neighbours of `id`: the ends of its edges and the other members of its groups. */
export function neighboursOf(data: GraphData, id: string): Set<string> {
  const out = new Set<string>();
  for (const edge of data.edges) {
    if (edge.a === id) out.add(edge.b);
    else if (edge.b === id) out.add(edge.a);
  }
  return out;
}

export function nodeOf(nodes: readonly GraphNode[], id: string): GraphNode | undefined {
  return nodes.find((node) => node.session_id === id);
}

/** What the pointer (or the keyboard) is on, which the tooltip describes. */
export type Tip =
  | { kind: "node"; id: string }
  | { kind: "edge"; a: string; b: string }
  | { kind: "group"; name: string }
  | { kind: "packet"; key: string; message: GraphMessage };
