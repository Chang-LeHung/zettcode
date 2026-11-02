// The Graph page's data: the roster, the groups, the pair totals and the latest messages. The page reads it once and
// then keeps it by the events the socket brings: a `traffic` event is counted in place, a `graph` event (the roster or
// the groups changed) reads everything again.

import { computed, markRaw, reactive } from "vue";
import { gateway } from "../api/gateway";
import { applyTrafficTo, deriveNodes, emptyGraph } from "../lib/graphData";
import { buildReplay, compress, due, fit30, stateAt, type Replay, type ReplayState } from "../lib/graphReplay";
import type { GraphData, GraphMessage } from "../types";

export const graph = reactive({
  ...emptyGraph(),
  loaded: false,
  /** The last read failed: what is shown may be out of date. */
  failed: false,
  /** A replay is on: live traffic is kept in the data but the view must not animate it. */
  liveMuted: false,
  /** The live feed, oldest first: the latest messages, with older ones added as the reader scrolls back. */
  feed: [] as GraphMessage[],
  /** Older messages are stored than the feed holds. */
  more: false,
  loadingOlder: false,
  olderFailed: false,
});

/** The most messages the feed keeps; past it the newest are kept and the reader can scroll back for the rest. */
const FEED_LIMIT = 2000;
/** The page size of the broker's `recent`, which is also what a feed that is shorter than it has nothing before. */
const PAGE = 50;

function addToFeed(message: GraphMessage): void {
  if (graph.feed.some((known) => known.id === message.id)) return;
  graph.feed.push(message);
  graph.feed.sort((a, b) => a.id - b.id);
  if (graph.feed.length > FEED_LIMIT) graph.feed.splice(0, graph.feed.length - FEED_LIMIT);
}

/** Add the messages stored before the oldest one the feed holds. Does nothing while one load is on, or when none remain. */
export async function loadOlder(): Promise<void> {
  const oldest = graph.feed[0];
  if (!oldest || !graph.more || graph.loadingOlder) return;
  graph.loadingOlder = true;
  graph.olderFailed = false;
  try {
    const page = await gateway.older(oldest.id, PAGE);
    const held = new Set(graph.feed.map((message) => message.id));
    graph.feed.unshift(...page.messages.filter((message) => !held.has(message.id)));
    graph.more = page.more;
  } catch {
    graph.olderFailed = true;
  } finally {
    graph.loadingOlder = false;
  }
}

export const graphNodes = computed(() => deriveNodes(graph));

type Listener = (message: GraphMessage) => void;
const listeners = new Set<Listener>();

/** Be told of each new message as it arrives (not of the ones a read brings), to animate it. Returns the way to stop. */
export function onTraffic(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** What the user asked to look at: a message to play again, and the message whose nodes are lit. */
export const graphUi = reactive({
  replay: null as { message: GraphMessage; n: number } | null,
  spotlight: null as GraphMessage | null,
});

let replays = 0;
let spotlightTimer: ReturnType<typeof setTimeout> | undefined;

/** Play a message again and light the nodes it touched for a moment. */
export function replay(message: GraphMessage): void {
  replays += 1;
  graphUi.replay = { message, n: replays };
  graphUi.spotlight = message;
  clearTimeout(spotlightTimer);
  spotlightTimer = setTimeout(() => (graphUi.spotlight = null), 2600);
}

// Messages that arrive while a read is on the way may be older or newer than what it returns; the newer ones are
// counted again afterwards, because the broker's ids only grow.
let loading = 0;
let held: GraphMessage[] = [];

export function applyGraph(data: GraphData): void {
  graph.sessions = data.sessions;
  graph.groups = data.groups;
  graph.edges = data.edges;
  graph.recent = data.recent.slice(-50);
  graph.feed = [...data.recent];
  graph.more = data.recent.length >= PAGE;
  graph.olderFailed = false;
  graph.loaded = true;
  graph.failed = false;
}

export function applyTraffic(message: GraphMessage): void {
  if (loading) held.push(message);
  if (!applyTrafficTo(graph, message)) return;
  addToFeed(message);
  if (!graph.liveMuted) for (const listener of [...listeners]) listener(message);
}

export async function loadGraph(): Promise<void> {
  loading += 1;
  try {
    const data = await gateway.graph();
    const newest = data.recent.reduce((id, message) => Math.max(id, message.id), 0);
    const later = held.filter((message) => message.id > newest);
    applyGraph(data);
    for (const message of later) if (applyTrafficTo(graph, message)) addToFeed(message);
  } catch (error) {
    graph.failed = true;
    throw error;
  } finally {
    loading -= 1;
    if (!loading) held = [];
  }
}

export function resetGraph(): void {
  Object.assign(graph, emptyGraph(), {
    loaded: false,
    failed: false,
    liveMuted: false,
    feed: [],
    more: false,
    loadingOlder: false,
    olderFailed: false,
  });
  exitReplay();
  held = [];
  loading = 0;
}

/** The replay of a past window: `mode` says which one the page shows; the rest is meaningful in "replay" only. */
export const graphReplay = reactive({
  mode: "live" as "live" | "replay",
  status: "idle" as "idle" | "loading" | "error" | "ready",
  replay: null as Replay | null,
  /** The playhead, real epoch seconds. */
  playhead: 0,
  playing: false,
  /** Playback seconds per second of the viewer's clock. */
  speed: 60,
  skipSilence: true,
  error: "",
  /** The window held more messages than were read, so the replay starts later than the window does. */
  truncated: false,
});

let loadToken = 0;

/** Read the stored traffic of [since, until] and enter replay mode, paused at the start. */
export async function loadReplay(since: number, until: number): Promise<void> {
  const token = ++loadToken;
  graphReplay.mode = "replay";
  graph.liveMuted = true;
  graphReplay.status = "loading";
  graphReplay.playing = false;
  graphReplay.error = "";
  try {
    const timeline = await gateway.timeline(since, until);
    if (token !== loadToken) return;
    const built = markRaw(buildReplay(timeline.messages, since, until));
    graphReplay.replay = built;
    graphReplay.truncated = timeline.truncated === true;
    graphReplay.playhead = built.start;
    graphReplay.status = "ready";
  } catch (error) {
    if (token !== loadToken) return;
    graphReplay.status = "error";
    graphReplay.error = error instanceof Error ? error.message : String(error);
  }
}

/** Leave replay and return to live; any read still on the way is dropped. */
export function exitReplay(): void {
  loadToken += 1;
  graphReplay.mode = "live";
  graphReplay.status = "idle";
  graphReplay.replay = null;
  graphReplay.truncated = false;
  graphReplay.playhead = 0;
  graphReplay.playing = false;
  graphReplay.error = "";
  graph.liveMuted = false;
}

/** Move the playhead to real time `t`, clamped to the window. */
export function seek(t: number): void {
  const r = graphReplay.replay;
  if (!r) return;
  graphReplay.playhead = Math.min(r.end, Math.max(r.start, t));
}

export function play(): void {
  const r = graphReplay.replay;
  if (!r) return;
  if (graphReplay.playhead >= r.end) graphReplay.playhead = r.start;
  graphReplay.playing = true;
}

export function pause(): void {
  graphReplay.playing = false;
}

export function setSpeed(speed: number): void {
  if (speed > 0) graphReplay.speed = speed;
}

/** Play the whole window in about 30 seconds. */
export function setSpeedFit30(): void {
  if (graphReplay.replay) graphReplay.speed = fit30(graphReplay.replay);
}

export function toggleSkip(): void {
  graphReplay.skipSilence = !graphReplay.skipSilence;
}

/**
 * Advance the playhead by `dt` seconds of the viewer's clock (at the speed, squeezing silences when asked) and return
 * the messages that became due. Pauses at the end. Does nothing unless playing.
 */
export function tick(dt: number): GraphMessage[] {
  const r = graphReplay.replay;
  if (!r || !graphReplay.playing || dt <= 0) return [];
  const clock = compress(r, graphReplay.speed, graphReplay.skipSilence);
  const from = graphReplay.playhead;
  const to = clock.toReal(clock.toPlayback(from) + dt);
  graphReplay.playhead = to;
  if (to >= r.end) graphReplay.playing = false;
  return due(r, from, to);
}

/** What the graph shows at the playhead, or null outside replay. */
export const replayState = computed<ReplayState | null>(() =>
  graphReplay.mode === "replay" && graphReplay.replay ? stateAt(graphReplay.replay, graphReplay.playhead) : null,
);
