<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, shallowRef, watch } from "vue";
import { t } from "../../i18n";
import { PALETTE, hueOf, initialsOf } from "../../lib/avatar";
import {
  approach,
  clampTooltip,
  curvePath,
  edgeCurve,
  edgeStyle,
  hueOfName,
  hullLabelAnchor,
  layoutCircle,
  pairKey,
  polygonPath,
  preview,
  roundedHull,
  type Curve,
  type Point,
} from "../../lib/graph";
import { replayGroups, replayNodes } from "../../lib/graphBar";
import { neighboursOf, reached, type GraphNode, type Tip } from "../../lib/graphData";
import { formatClock, recentTail } from "../../lib/graphReplay";
import { FxEngine, type FxFrame } from "../../lib/graphFx";
import { exitReplay, graph, graphNodes, graphReplay, graphUi, loadGraph, onTraffic, replay, replayState, tick as replayTick } from "../../stores/graph";
import { lobby } from "../../stores/threads";
import type { GraphMessage, Via } from "../../types";
import Icon from "../common/Icon.vue";
import PageBar from "../common/PageBar.vue";
import GraphPanel from "./GraphPanel.vue";
import GraphTip from "./GraphTip.vue";
import ReplayBar from "./ReplayBar.vue";

const stage = ref<HTMLElement | null>(null);
const tipEl = ref<HTMLElement | null>(null);
const size = reactive({ width: 0, height: 0 });
const now = ref(Date.now() / 1000);
const sheet = ref(false);

// What the bars take: the replay badge above, and below the replay button or, in a replay, the whole player.
const insets = computed(() => {
  const replaying = graphReplay.mode === "replay";
  return { top: replaying ? 56 : 0, bottom: replaying ? (compact.value ? 150 : 138) : 64 };
});
const compact = computed(() => Math.min(size.width, size.height) < 520);
const radius = computed(() => (compact.value ? 18 : 22));
const inReplay = computed(() => graphReplay.mode === "replay" && !!replayState.value);

// In replay the roster is the sessions of the window (those gone now are ghosts); live, it is the live roster.
const nodesNow = computed<GraphNode[]>(() => {
  const state = replayState.value;
  return state && graphReplay.replay ? replayNodes(graphReplay.replay, state, graph.sessions) : graphNodes.value;
});
const edgesNow = computed(() => replayState.value?.edges ?? graph.edges);
const groupsNow = computed(() => {
  const state = replayState.value;
  return state ? replayGroups(state.shown, state.groupsTouched, graph.groups) : graph.groups;
});
const targets = computed(() => layoutCircle(nodesNow.value.map((node) => node.session_id), size, compact.value ? 66 : 100, insets.value));

// --- positions: the nodes glide to their places on the ring when the ring changes ------------------------------------

const shown = shallowRef(new Map<string, Point>());
const frame = shallowRef<FxFrame>({ packets: [], pulses: [] });
const engine = new FxEngine();
let raf = 0;
let last = 0;
let snapNext = true;
const REPLAY_BURST = 8;
// The playhead the loop left; a different value means the user moved it (a seek).
let expected = 0;
let ticking = false;

const reducedMotion = (): boolean => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

function at(id: string): Point | undefined {
  return shown.value.get(id) ?? targets.value.get(id);
}

function curveOf(from: string, to: string): Curve | null {
  const a = at(from);
  const b = at(to);
  return a && b ? edgeCurve(from, a, to, b) : null;
}

function kick(): void {
  if (raf || document.hidden) return;
  last = performance.now();
  raf = requestAnimationFrame(tick);
}

function tick(ts: number): void {
  raf = 0;
  const dt = Math.min(0.05, Math.max(0, (ts - last) / 1000));
  last = ts;
  let moving = false;
  const next = new Map<string, Point>();
  for (const [id, target] of targets.value) {
    const current = shown.value.get(id);
    if (!current) {
      next.set(id, target);
      continue;
    }
    const x = approach(current.x, target.x, dt);
    const y = approach(current.y, target.y, dt);
    if (x !== target.x || y !== target.y) moving = true;
    next.set(id, { x, y });
  }
  shown.value = next;
  let playing = false;
  if (graphReplay.mode === "replay" && graphReplay.playing && !document.hidden) {
    playing = true;
    ticking = true;
    const due = replayTick(dt);
    ticking = false;
    expected = graphReplay.playhead;
    // At high speeds a frame can pass hundreds of messages: the last few are shown, as the cap does live.
    for (const message of due.slice(-REPLAY_BURST)) play(message);
  }
  if (engine.busy) frame.value = engine.step(ts, curveOf);
  else if (frame.value.packets.length || frame.value.pulses.length) frame.value = { packets: [], pulses: [] };
  if (moving || engine.busy || playing) raf = requestAnimationFrame(tick);
}

watch(targets, (value) => {
  if (snapNext || reducedMotion() || !shown.value.size) {
    shown.value = new Map(value);
    snapNext = false;
  }
  kick();
});

// --- animation of the traffic ----------------------------------------------------------------------------------------

function play(message: GraphMessage): void {
  if (document.hidden) return;
  engine.spawn(message, performance.now(), reducedMotion());
  kick();
}

let stopTraffic: (() => void) | undefined;

watch(
  () => graphUi.replay,
  (request) => {
    if (request && !inReplay.value) play(request.message);
  },
);

// A seek shows only the last second before the playhead, not everything that was skipped.
watch(
  () => graphReplay.playhead,
  (head) => {
    if (ticking || head === expected) return;
    expected = head;
    engine.clear();
    frame.value = { packets: [], pulses: [] };
    if (graphReplay.mode === "replay" && graphReplay.replay) for (const message of recentTail(graphReplay.replay, head, 1).slice(-REPLAY_BURST)) play(message);
    kick();
  },
  { flush: "sync" },
);

watch(
  () => graphReplay.playing,
  (on) => {
    if (on) kick();
  },
);

watch(
  () => graphReplay.mode,
  () => {
    engine.clear();
    frame.value = { packets: [], pulses: [] };
    snapNext = true;
    hover.value = null;
    kick();
  },
);

function onVisible(): void {
  if (document.hidden) {
    engine.clear();
    frame.value = { packets: [], pulses: [] };
    return;
  }
  shown.value = new Map(targets.value);
  now.value = Date.now() / 1000;
  kick();
}

// --- what is drawn -------------------------------------------------------------------------------------------------------

interface Placed {
  id: string;
  x: number;
  y: number;
  handle: string;
  label: string;
  initials: string;
  hue: number;
  working: boolean;
  external: boolean;
  ghost: boolean;
  aria: string;
}

const placed = computed<Placed[]>(() =>
  nodesNow.value.flatMap((node) => {
    const p = at(node.session_id);
    if (!p) return [];
    const state = node.ghost ? t("offline") : t(node.status);
    return [
      {
        id: node.session_id,
        x: p.x,
        y: p.y,
        handle: node.handle,
        label: preview(node.handle, 18),
        initials: initialsOf((node.handle || node.title || "?").replace(/^[^\p{L}\p{N}]+/u, "") || "?"),
        hue: hueOf(node.session_id),
        working: !node.ghost && node.status === "working",
        external: node.kind === "external",
        ghost: node.ghost,
        aria: `${node.handle}, ${state}${node.kind === "external" ? `, ${t("external")}` : ""}`,
      },
    ];
  }),
);

const ids = computed(() => new Set(nodesNow.value.map((node) => node.session_id)));

const clockNow = computed(() => (inReplay.value ? graphReplay.playhead : now.value));

const edges = computed(() =>
  edgesNow.value.flatMap((edge) => {
    const a = at(edge.a);
    const b = at(edge.b);
    if (!a || !b || !ids.value.has(edge.a) || !ids.value.has(edge.b)) return [];
    const style = edgeStyle(edge.count, edge.last, clockNow.value);
    return [{ key: pairKey(edge.a, edge.b), a: edge.a, b: edge.b, d: curvePath(edgeCurve(edge.a, a, edge.b, b)), ...style }];
  }),
);

const middle = computed<Point>(() => ({ x: size.width / 2, y: size.height / 2 }));

function pillWidth(name: string): number {
  let w = 22;
  for (const char of name) w += (char.codePointAt(0) ?? 0) > 0x2e7f ? 12.5 : 6.6;
  return w;
}

const hulls = computed(() =>
  groupsNow.value.flatMap((group) => {
    const points = group.members.map((id) => at(id)).filter((p): p is Point => p !== undefined);
    const present = group.members.filter((id) => ids.value.has(id));
    if (!points.length || !present.length) return [];
    const polygon = roundedHull(points, radius.value + 17);
    const anchor = hullLabelAnchor(polygon, points, middle.value);
    const width = pillWidth(group.name);
    return [{ name: group.name, hue: hueOfName(group.name), d: polygonPath(polygon), x: anchor.x, y: anchor.y, width, count: present.length }];
  }),
);

// What the pointer or the keyboard is on dims the rest.
const hover = ref<Tip | null>(null);
const anchor = ref<Point>({ x: 0, y: 0 });
const tipSize = ref({ width: 0, height: 0 });

interface Focus {
  nodes: Set<string>;
  edge(a: string, b: string): boolean;
}

const focus = computed<Focus | null>(() => {
  const tip = hover.value;
  if (tip?.kind === "node") {
    const near = neighboursOf({ ...graph, edges: edgesNow.value }, tip.id);
    near.add(tip.id);
    return { nodes: near, edge: (a, b) => a === tip.id || b === tip.id };
  }
  if (tip?.kind === "edge") return { nodes: new Set([tip.a, tip.b]), edge: (a, b) => pairKey(a, b) === pairKey(tip.a, tip.b) };
  if (tip?.kind === "group") {
    const members = new Set(groupsNow.value.find((group) => group.name === tip.name)?.members ?? []);
    return { nodes: members, edge: (a, b) => members.has(a) && members.has(b) };
  }
  const spot = graphUi.spotlight;
  if (spot) {
    const from = spot.from.session_id;
    const to = new Set(reached(spot));
    return {
      nodes: new Set([from, ...to]),
      edge: (a, b) => (a === from && to.has(b)) || (b === from && to.has(a)),
    };
  }
  return null;
});

const viaColor = (via: Via): string => `var(--via-${via})`;

const fx = computed(() => {
  const out = {
    packets: frame.value.packets.map((packet) => ({ ...packet, color: viaColor(packet.via) })),
    rings: [] as { key: string; x: number; y: number; r: number; opacity: number; color: string }[],
    glows: [] as { key: string; d: string; opacity: number; color: string }[],
    hulls: [] as { key: string; d: string; opacity: number; color: string }[],
  };
  for (const pulse of frame.value.pulses) {
    const p = Math.min(1, Math.max(0, pulse.progress));
    const color = viaColor(pulse.via);
    if (pulse.kind === "flash" || pulse.kind === "ripple") {
      const pos = at(pulse.target);
      if (!pos) continue;
      const base = radius.value;
      if (pulse.kind === "flash") {
        out.rings.push({ key: pulse.key, x: pos.x, y: pos.y, r: base + 4 + (pulse.grow ? p * 12 : 0), opacity: 1 - p, color });
      } else if (pulse.grow) {
        out.rings.push({ key: `${pulse.key}a`, x: pos.x, y: pos.y, r: base + 3 + p * 36, opacity: (1 - p) * 0.9, color });
        const q = Math.max(0, (p - 0.22) / 0.78);
        if (q > 0) out.rings.push({ key: `${pulse.key}b`, x: pos.x, y: pos.y, r: base + 3 + q * 36, opacity: (1 - q) * 0.6, color });
      } else {
        out.rings.push({ key: pulse.key, x: pos.x, y: pos.y, r: base + 6, opacity: 1 - p, color });
      }
    } else if (pulse.kind === "edge" && pulse.other) {
      const curve = curveOf(pulse.target, pulse.other);
      if (curve) out.glows.push({ key: pulse.key, d: curvePath(curve), opacity: Math.sin(Math.PI * p), color });
    } else if (pulse.kind === "hull") {
      const hull = hulls.value.find((candidate) => candidate.name === pulse.target);
      if (hull) out.hulls.push({ key: pulse.key, d: hull.d, opacity: Math.sin(Math.PI * p), color });
    }
  }
  return out;
});

watch(frame, (value) => {
  const tip = hover.value;
  if (tip?.kind === "packet" && !value.packets.some((packet) => packet.key === tip.key)) hover.value = null;
});

// --- the tooltip ---------------------------------------------------------------------------------------------------------

let clearTimer: ReturnType<typeof setTimeout> | undefined;

function point(event: MouseEvent): Point {
  const box = stage.value?.getBoundingClientRect();
  return { x: event.clientX - (box?.left ?? 0), y: event.clientY - (box?.top ?? 0) };
}

function enter(tip: Tip, event?: MouseEvent): void {
  clearTimeout(clearTimer);
  hover.value = tip;
  if (event) anchor.value = point(event);
}

function leave(): void {
  clearTimeout(clearTimer);
  // A moment of grace, so crossing from a line to a node does not blink the card.
  clearTimer = setTimeout(() => (hover.value = null), 70);
}

function focusNode(node: Placed): void {
  enter({ kind: "node", id: node.id });
  anchor.value = { x: node.x + radius.value * 0.6, y: node.y + radius.value * 0.6 };
}

function move(event: MouseEvent): void {
  if (hover.value) anchor.value = point(event);
}

watch(
  hover,
  async () => {
    await nextTick();
    if (tipEl.value) tipSize.value = { width: tipEl.value.offsetWidth, height: tipEl.value.offsetHeight };
  },
  { flush: "post" },
);

const tipStyle = computed(() => {
  const p = clampTooltip(anchor.value, tipSize.value, size);
  return { transform: `translate(${Math.round(p.x)}px, ${Math.round(p.y)}px)` };
});

// --- the page -------------------------------------------------------------------------------------------------------------

const lastMessage = computed(() => graph.recent[graph.recent.length - 1]);
const empty = computed(() => !inReplay.value && graphNodes.value.length < 2);
const range = computed(() => {
  const r = graphReplay.replay;
  return r ? t("REPLAY — {from} → {to}", { from: stamp(r.start), to: stamp(r.end) }) : t("REPLAY");
});

function stamp(ts: number): string {
  const d = new Date(ts * 1000);
  return `${d.toLocaleDateString()} ${formatClock(ts).slice(0, 5)}`;
}
const unreachable = computed(() => lobby.status?.broker.reachable === false);
const summary = computed(() =>
  t("{sessions} sessions · {groups} groups", { sessions: graph.sessions.length, groups: graph.groups.length }),
);

let observer: ResizeObserver | undefined;
let clock: ReturnType<typeof setInterval> | undefined;

onMounted(() => {
  const el = stage.value;
  const measure = (): void => {
    if (!el) return;
    const next = { width: Math.round(el.clientWidth), height: Math.round(el.clientHeight) };
    if (next.width !== size.width || next.height !== size.height) {
      snapNext = true;
      Object.assign(size, next);
    }
  };
  measure();
  if (el && typeof ResizeObserver !== "undefined") {
    observer = new ResizeObserver(measure);
    observer.observe(el);
  }
  document.addEventListener("visibilitychange", onVisible);
  clock = setInterval(() => (now.value = Date.now() / 1000), 10_000);
  stopTraffic = onTraffic(play);
  shown.value = new Map(targets.value);
  if (!graph.loaded) void loadGraph().catch(() => {});
});

onUnmounted(() => {
  observer?.disconnect();
  stopTraffic?.();
  exitReplay();
  document.removeEventListener("visibilitychange", onVisible);
  clearInterval(clock);
  clearTimeout(clearTimer);
  cancelAnimationFrame(raf);
  engine.clear();
});

function retry(): void {
  void loadGraph().catch(() => {});
}
</script>

<template>
  <PageBar :title="t('Graph')">
    <span class="gv-summary">{{ summary }}</span>
    <button
      class="iconbtn"
      :disabled="!lastMessage || inReplay"
      :title="t('Replay the last message')"
      :aria-label="t('Replay the last message')"
      @click="lastMessage && replay(lastMessage)"
    >
      <Icon name="refresh" />
    </button>
    <button class="iconbtn gv-feedbtn" :aria-label="t('Live messages')" @click="sheet = !sheet"><Icon name="text" /></button>
  </PageBar>

  <div ref="stage" class="gv" :class="{ focus: !!focus }" @mousemove="move">
    <svg v-if="size.width" class="gv-svg" role="group" :aria-label="t('Session graph')" :viewBox="`0 0 ${size.width} ${size.height}`" :width="size.width" :height="size.height">
      <defs>
        <linearGradient v-for="(pair, index) in PALETTE" :id="`gv-av${index}`" :key="index" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" :stop-color="pair[0]" />
          <stop offset="1" :stop-color="pair[1]" />
        </linearGradient>
        <radialGradient v-for="via in ['user', 'agent', 'external']" :id="`gv-glow-${via}`" :key="via">
          <stop offset="0" :style="{ stopColor: `var(--via-${via})`, stopOpacity: 0.85 }" />
          <stop offset="1" :style="{ stopColor: `var(--via-${via})`, stopOpacity: 0 }" />
        </radialGradient>
        <filter id="gv-blur" x="-60%" y="-60%" width="220%" height="220%"><feGaussianBlur stdDeviation="7" /></filter>
      </defs>

      <g class="gv-hulls">
        <g v-for="hull in hulls" :key="hull.name" :style="{ '--h': hull.hue }" class="ghull" :class="{ dim: focus && hover?.kind !== 'group' }">
          <path class="ghull-fill" :d="hull.d" />
          <path class="ghull-hit" :d="hull.d" @mouseenter="enter({ kind: 'group', name: hull.name }, $event)" @mouseleave="leave" />
        </g>
        <path v-for="glow in fx.hulls" :key="glow.key" class="gfx-hull" :d="glow.d" :style="{ stroke: glow.color, fill: glow.color, opacity: glow.opacity }" />
      </g>

      <g class="gv-edges">
        <g v-for="edge in edges" :key="edge.key" class="gedge" :class="{ hot: focus?.edge(edge.a, edge.b), dim: focus && !focus.edge(edge.a, edge.b) }">
          <path class="gedge-line" :d="edge.d" :style="{ strokeWidth: edge.width, opacity: edge.opacity }" />
          <path class="gedge-hit" :d="edge.d" @mouseenter="enter({ kind: 'edge', a: edge.a, b: edge.b }, $event)" @mouseleave="leave" />
        </g>
        <g class="gv-glows">
          <g v-for="glow in fx.glows" :key="glow.key" :style="{ opacity: glow.opacity, stroke: glow.color }">
            <path class="gfx-glow wide" :d="glow.d" />
            <path class="gfx-glow" :d="glow.d" />
          </g>
        </g>
      </g>

      <g class="gv-nodes">
        <g
          v-for="node in placed"
          :key="node.id"
          class="gnode"
          :class="{ dim: focus && !focus.nodes.has(node.id), ghost: node.ghost, working: node.working }"
          :transform="`translate(${node.x} ${node.y})`"
          tabindex="0"
          role="img"
          :aria-label="node.aria"
          @mouseenter="enter({ kind: 'node', id: node.id }, $event)"
          @mouseleave="leave"
          @focus="focusNode(node)"
          @blur="leave"
        >
          <circle class="gnode-halo" :r="radius + 6" :fill="PALETTE[node.hue]![1]" filter="url(#gv-blur)" />
          <circle v-if="node.working" class="gnode-aura" :r="radius + 5" />
          <circle class="gnode-ring" :class="node.ghost ? 'off' : node.working ? 'working' : 'idle'" :r="radius + 5" />
          <circle class="gnode-face" :r="radius" :fill="node.ghost ? 'var(--surface-2)' : `url(#gv-av${node.hue})`" />
          <text class="gnode-text" dy="0.35em" :style="{ fontSize: `${radius * 0.62}px` }">{{ node.initials }}</text>
          <g v-if="node.external" class="gnode-badge" :transform="`translate(${radius * 0.78} ${-radius * 0.78})`">
            <circle r="8" />
            <path d="M-2.6 2.6 2.6 -2.6M-1 -2.6H2.6V1" />
          </g>
          <text class="gnode-label" :y="radius + 19">{{ node.label }}</text>
        </g>
      </g>

      <g class="gv-pills">
        <g
          v-for="hull in hulls"
          :key="hull.name"
          class="gpill"
          :class="{ dim: focus && hover?.kind !== 'group' }"
          :style="{ '--h': hull.hue }"
          :transform="`translate(${hull.x} ${hull.y})`"
          @mouseenter="enter({ kind: 'group', name: hull.name }, $event)"
          @mouseleave="leave"
        >
          <rect :x="-hull.width / 2" y="-11" :width="hull.width" height="22" rx="11" />
          <text dy="0.35em">#{{ hull.name }}</text>
        </g>
      </g>

      <g class="gv-fx">
        <circle v-for="ring in fx.rings" :key="ring.key" class="gfx-ring" :cx="ring.x" :cy="ring.y" :r="ring.r" :style="{ stroke: ring.color, opacity: ring.opacity }" />
        <g v-for="packet in fx.packets" :key="packet.key" class="gpacket">
          <circle v-for="(dot, index) in packet.trail" :key="index" :cx="dot.x" :cy="dot.y" :r="4.2 * dot.scale" :style="{ fill: packet.color, opacity: dot.alpha }" />
          <g :transform="`translate(${packet.x} ${packet.y})`">
            <circle r="15" :fill="`url(#gv-glow-${packet.via})`" />
            <circle class="gpacket-core" r="4.6" :style="{ stroke: packet.color }" />
            <circle
              class="gpacket-hit"
              r="13"
              @mouseenter="enter({ kind: 'packet', key: packet.key, message: packet.message }, $event)"
              @mouseleave="leave"
            />
          </g>
        </g>
      </g>
    </svg>

    <div v-if="hover" ref="tipEl" class="gv-tip" :style="tipStyle" role="tooltip"><GraphTip :tip="hover" :now="clockNow" /></div>

    <div v-if="graphReplay.mode === 'replay'" class="gv-badge" role="status">
      <i class="gv-dot" /><b>{{ range }}</b>
      <button class="btn ghost sm" @click="exitReplay">{{ t("Back to live") }}</button>
    </div>
    <ReplayBar />

    <div v-if="unreachable && !inReplay" class="gv-banner bad"><Icon name="warn" size="sm" />{{ t("The broker is not reachable, so this may be out of date.") }}</div>
    <div v-else-if="graph.failed && !inReplay" class="gv-banner">
      <Icon name="warn" size="sm" />{{ t("Cannot load the graph.") }}
      <button class="btn ghost sm" @click="retry">{{ t("Retry") }}</button>
    </div>

    <div v-if="graph.loaded && empty" class="gv-empty">
      <b>{{ t("No other sessions are running") }}</b>
      <span>{{ t("Start another session and the messages between them will appear here as they happen.") }}</span>
    </div>

    <div v-if="sheet" class="gv-scrim" @click="sheet = false" />
    <aside v-if="sheet" class="gv-sheet" :aria-label="t('Live messages')">
      <button class="iconbtn gv-close" :aria-label="t('Close')" @click="sheet = false"><Icon name="close" /></button>
      <GraphPanel @pick="sheet = false" />
    </aside>
  </div>
</template>

<style>
.gv-summary { margin-right: 6px; font-size: 0.78rem; color: var(--muted); white-space: nowrap; }
.gv-feedbtn { display: none; }
.gv {
  position: relative; flex: 1; min-height: 0; overflow: hidden; background-color: var(--graph-bg);
  background-image:
    radial-gradient(ellipse 70% 60% at 50% 50%, color-mix(in srgb, var(--accent) 7%, transparent), transparent 70%),
    radial-gradient(circle at 1px 1px, var(--graph-dot) 1px, transparent 1.2px);
  background-size: auto, 22px 22px;
}
.gv-svg { position: absolute; inset: 0; display: block; user-select: none; -webkit-user-select: none; }

.ghull-fill { fill: hsl(var(--h) 75% 55% / 0.1); stroke: hsl(var(--h) 75% 55% / 0.5); stroke-width: 1.3; stroke-dasharray: 5 5; transition: opacity 0.2s; }
.ghull-hit { fill: none; stroke: transparent; stroke-width: 16; pointer-events: stroke; }
.ghull.dim, .gpill.dim { opacity: 0.28; }
.ghull, .gpill { transition: opacity 0.2s; }
.gpill { cursor: default; }
.gpill rect { fill: hsl(var(--h) 60% 22% / 0.92); stroke: hsl(var(--h) 75% 62% / 0.7); stroke-width: 1; }
.gpill text { fill: hsl(var(--h) 90% 88%); font-size: 11.5px; font-weight: 600; text-anchor: middle; pointer-events: none; }
:root[data-theme="light"] .gpill rect { fill: hsl(var(--h) 80% 95% / 0.96); stroke: hsl(var(--h) 60% 48% / 0.6); }
:root[data-theme="light"] .gpill text { fill: hsl(var(--h) 70% 30%); }
@media (prefers-color-scheme: light) {
  :root:not([data-theme="dark"]) .gpill rect { fill: hsl(var(--h) 80% 95% / 0.96); stroke: hsl(var(--h) 60% 48% / 0.6); }
  :root:not([data-theme="dark"]) .gpill text { fill: hsl(var(--h) 70% 30%); }
}
.gfx-hull { stroke-width: 2.5; fill-opacity: 0.08; pointer-events: none; }

.gedge { transition: opacity 0.2s; }
.gedge-line { fill: none; stroke: var(--graph-edge); stroke-linecap: round; transition: opacity 0.2s, stroke-width 0.2s; }
.gedge.hot .gedge-line { stroke: var(--accent); opacity: 1 !important; }
.gedge.dim { opacity: 0.2; }
.gedge-hit { fill: none; stroke: transparent; stroke-width: 14; pointer-events: stroke; }
.gfx-glow { fill: none; stroke: inherit; stroke-width: 2.2; stroke-linecap: round; pointer-events: none; }
.gfx-glow.wide { stroke-width: 7; opacity: 0.25; }

.gnode { cursor: default; outline: none; transition: opacity 0.2s; }
.gnode.dim { opacity: 0.32; }
.gnode.ghost { opacity: 0.55; }
.gnode.ghost.dim { opacity: 0.2; }
.gnode-halo { opacity: 0.28; pointer-events: none; }
.gnode.ghost .gnode-halo { opacity: 0; }
.gnode-ring { fill: none; stroke-width: 2.4; }
.gnode-ring.idle { stroke: var(--ok); opacity: 0.85; }
.gnode-ring.working { stroke: var(--warn); animation: gv-ring 1.5s ease-in-out infinite; }
.gnode-ring.off { stroke: var(--muted); stroke-dasharray: 3 4; opacity: 0.7; }
.gnode-aura { fill: none; stroke: var(--warn); stroke-width: 1.5; transform-box: fill-box; transform-origin: center; animation: gv-aura 1.5s ease-out infinite; }
.gnode-face { stroke: var(--graph-bg); stroke-width: 2; transition: stroke 0.15s; }
.gnode:hover .gnode-face, .gnode:focus-visible .gnode-face { stroke: var(--text); }
.gnode:focus-visible .gnode-ring { stroke: var(--accent); stroke-width: 3.2; opacity: 1; }
.gnode-text { fill: #fff; font-weight: 650; text-anchor: middle; pointer-events: none; letter-spacing: 0.02em; }
.gnode.ghost .gnode-text { fill: var(--muted); }
.gnode-label { fill: var(--text); font-size: 12px; font-weight: 550; text-anchor: middle; paint-order: stroke; stroke: var(--graph-bg); stroke-width: 4px; stroke-linejoin: round; pointer-events: none; }
.gnode-badge circle { fill: var(--graph-bg); stroke: var(--via-external); stroke-width: 1.6; }
.gnode-badge path { fill: none; stroke: var(--via-external); stroke-width: 1.6; stroke-linecap: round; stroke-linejoin: round; }
@keyframes gv-ring { 0%, 100% { opacity: 0.55; stroke-width: 2.2; } 50% { opacity: 1; stroke-width: 3.6; } }
@keyframes gv-aura { from { transform: scale(1); opacity: 0.7; } to { transform: scale(1.7); opacity: 0; } }

.gfx-ring { fill: none; stroke-width: 2.4; pointer-events: none; }
.gpacket circle { pointer-events: none; }
.gpacket-core { fill: #fff; stroke-width: 2; }
.gpacket .gpacket-hit { fill: transparent; stroke: none; pointer-events: all; cursor: help; }

.gv-tip {
  position: absolute; left: 0; top: 0; z-index: 4; width: max-content; max-width: min(320px, calc(100% - 16px)); padding: 11px 13px; border-radius: 12px;
  background: var(--graph-card); border: 1px solid var(--graph-card-border); box-shadow: var(--graph-shadow);
  -webkit-backdrop-filter: blur(14px); backdrop-filter: blur(14px); color: var(--text); pointer-events: none;
}
.gv-banner {
  position: absolute; top: 12px; left: 50%; transform: translateX(-50%); z-index: 3; display: flex; align-items: center; gap: 8px;
  max-width: calc(100% - 24px); padding: 7px 14px; border-radius: 999px; font-size: 0.82rem;
  background: var(--graph-card); border: 1px solid var(--graph-card-border); box-shadow: var(--graph-shadow); color: var(--warn);
}
.gv-badge {
  position: absolute; top: 12px; left: 50%; transform: translateX(-50%); z-index: 3; display: flex; align-items: center; gap: 10px; max-width: calc(100% - 24px);
  padding: 5px 6px 5px 14px; border-radius: 999px; font-size: 0.78rem; background: var(--graph-card); border: 1px solid var(--accent); box-shadow: var(--graph-shadow); color: var(--text);
}
.gv-badge b { font-weight: 650; letter-spacing: 0.04em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-variant-numeric: tabular-nums; }
.gv-badge .btn { min-height: 28px; padding: 0 12px; border-radius: 999px; }
.gv-dot { flex: none; width: 8px; height: 8px; border-radius: 50%; background: var(--bad); animation: pulse 1.4s ease-in-out infinite; }
.gv-banner.bad { color: var(--bad); }
.gv-empty {
  position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%); z-index: 1; width: min(340px, calc(100% - 48px));
  display: flex; flex-direction: column; gap: 6px; text-align: center; color: var(--muted); font-size: 0.85rem; line-height: 1.45; pointer-events: none;
  margin-top: 96px;
}
.gv-empty b { color: var(--text); font-size: 1rem; font-weight: 650; }

.gv-scrim { position: absolute; inset: 0; z-index: 5; background: var(--scrim); animation: fade 0.18s ease-out; }
.gv-sheet {
  position: absolute; left: 0; right: 0; bottom: 0; z-index: 6; height: min(72%, 560px); display: flex; flex-direction: column;
  padding-top: 14px; border-radius: 18px 18px 0 0; background: var(--surface); box-shadow: var(--sheet-shadow); animation: spring 0.3s ease-out;
}
.gv-close { position: absolute; right: 6px; top: 6px; width: 36px; height: 36px; z-index: 1; }

@media (max-width: 719px) {
  .gv-feedbtn { display: grid; }
  .gv-summary { display: none; }
  .gv-empty { margin-top: 70px; }
  .gv-badge { top: 8px; font-size: 0.72rem; }
  .gv-badge b { max-width: 60vw; }
}
@media (min-width: 720px) {
  .gv-sheet, .gv-scrim { display: none; }
}
@media (prefers-reduced-motion: reduce) {
  .gnode-ring.working, .gnode-aura { animation: none; }
  .gnode-aura { display: none; }
  .gv-dot { animation: none; }
}
</style>
