<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { t } from "../../i18n";
import { PALETTE, hueOf } from "../../lib/avatar";
import { duration } from "../../lib/format";
import { messagePreview, nodeOf, senderLabel, targetLabel, tipText, totals } from "../../lib/graphData";
import { formatClock } from "../../lib/graphReplay";
import { clampTooltip, hueOfName } from "../../lib/graph";
import { graph, graphNodes, graphReplay, loadOlder, replay, replayState, seek } from "../../stores/graph";
import type { GraphMessage } from "../../types";
import Icon from "../common/Icon.vue";

const emit = defineEmits<{ pick: [] }>();

const inReplay = computed(() => graphReplay.mode === "replay" && !!replayState.value);

function pick(message: GraphMessage): void {
  if (inReplay.value) {
    // Replay: jump the playhead to the message (the view lights it up).
    seek(message.ts);
    emit("pick");
    return;
  }
  replay(message);
  emit("pick");
}

const now = ref(Date.now() / 1000);
let timer: ReturnType<typeof setInterval> | undefined;
onMounted(() => (timer = setInterval(() => (now.value = Date.now() / 1000), 5000)));
onUnmounted(() => clearInterval(timer));

// Replay lists what the playhead has passed, newest first; live, the latest messages.
const feed = computed(() => {
  const shown = replayState.value?.shown;
  return shown ? shown.slice(-200).reverse() : [...graph.feed].reverse();
});
const counts = computed(() => totals(graph));

// Older messages are loaded when the list is scrolled to its end (newest first, so the end is the past), and again when
// a page did not fill the list and there is still more to read.
const list = ref<HTMLElement | null>(null);
function nearEnd(): boolean {
  const el = list.value;
  return !!el && el.scrollHeight - el.scrollTop - el.clientHeight < 120;
}
function more(): void {
  if (!inReplay.value && graph.more && nearEnd()) void loadOlder();
}
watch(
  () => [graph.feed.length, graph.more, inReplay.value],
  () => nextTick(more),
);
onMounted(() => nextTick(more));

// A card with the whole message, beside the row the pointer is on. It opens after a short pause and closes after a
// shorter one, so moving down the list does not make it flash, and it stays inside the window.
const card = ref<{ message: GraphMessage; x: number; y: number } | null>(null);
const cardEl = ref<HTMLElement | null>(null);
let openTimer: ReturnType<typeof setTimeout> | undefined;
let closeTimer: ReturnType<typeof setTimeout> | undefined;

function show(message: GraphMessage, event: MouseEvent | FocusEvent): void {
  clearTimeout(closeTimer);
  const row = (event.currentTarget as HTMLElement).getBoundingClientRect();
  openTimer = setTimeout(() => {
    card.value = { message, x: row.right + 10, y: row.top };
    void nextTick(place);
  }, card.value ? 0 : 280);
}
function keep(): void {
  clearTimeout(closeTimer);
}
function hide(): void {
  clearTimeout(openTimer);
  closeTimer = setTimeout(() => (card.value = null), 90);
}
function place(): void {
  const el = cardEl.value;
  const c = card.value;
  if (!el || !c) return;
  const spot = clampTooltip({ x: c.x, y: c.y }, { width: el.offsetWidth, height: el.offsetHeight }, { width: innerWidth, height: innerHeight }, 0, 8);
  el.style.left = `${spot.x}px`;
  el.style.top = `${spot.y}px`;
}
function names(message: GraphMessage): string {
  return message.recipients.map((id) => nodeOf(graphNodes.value, id)?.handle || id.slice(0, 8)).join(", ");
}
function exact(ts: number): string {
  return new Date(ts * 1000).toLocaleString();
}

function recipients(message: GraphMessage): number {
  return message.recipients.length;
}

function groupColor(message: GraphMessage): string {
  return `hsl(${hueOfName(message.to.name ?? "")} 70% 48%)`;
}

function ago(ts: number): string {
  const seconds = now.value - ts;
  if (inReplay.value) return formatClock(ts);
  return seconds < 5 ? t("just now") : t("{time} ago", { time: duration(seconds) });
}

function dot(id: string): string {
  const [a, b] = PALETTE[hueOf(id)]!;
  return `linear-gradient(160deg, ${a}, ${b})`;
}
</script>

<template>
  <div class="gp">
    <div class="gp-stats">
      <div><b>{{ counts.sessions }}</b><span>{{ t("Sessions") }}</span></div>
      <div><b>{{ counts.groups }}</b><span>{{ t("Groups") }}</span></div>
      <div><b>{{ counts.messages }}</b><span>{{ t("Messages") }}</span></div>
    </div>

    <div class="gp-legend" :aria-label="t('Legend')">
      <span class="gp-key"><i class="sw via-user" />{{ t("User") }}</span>
      <span class="gp-key"><i class="sw via-agent" />{{ t("Agent") }}</span>
      <span class="gp-key"><i class="sw via-external" />{{ t("External") }}</span>
      <span class="gp-key"><i class="ring idle" />{{ t("Idle") }}</span>
      <span class="gp-key"><i class="ring working" />{{ t("Working") }}</span>
      <span class="gp-key"><i class="hull" />{{ t("Group") }}</span>
    </div>

    <div class="gp-head">
      <h3>{{ inReplay ? t("Messages so far") : t("Live messages") }}</h3>
      <button v-if="feed.length && !inReplay" class="iconbtn gp-replay" :title="t('Replay the last message')" :aria-label="t('Replay the last message')" @click="pick(feed[0]!)">
        <Icon name="refresh" size="sm" />
      </button>
    </div>

    <div v-if="!feed.length" class="gp-none">{{ inReplay ? t("Nothing has been sent yet at this point.") : t("No messages yet. Traffic between sessions shows up here as it happens.") }}</div>
    <ol v-else ref="list" class="gp-feed" @scroll.passive="more">
      <li v-for="message in feed" :key="message.id">
        <button
          class="gp-item"
          :class="{ 'is-group': message.to.kind === 'group' }"
          :style="message.to.kind === 'group' ? { '--grp': groupColor(message) } : undefined"
          :title="inReplay ? t('Go to this message') : t('Replay')"
          @click="pick(message)"
          @mouseenter="show(message, $event)"
          @mouseleave="hide"
          @focus="show(message, $event)"
          @blur="hide"
        >
          <span v-if="message.to.kind === 'group'" class="gp-av gp-hash" aria-hidden="true">#</span>
          <span v-else class="gp-av" :style="{ background: dot(message.from.session_id) }" />
          <span class="gp-body">
            <span class="gp-line">
              <b>{{ senderLabel(message) }}</b><span class="gp-arrow">→</span
              ><b :class="{ grp: message.to.kind === 'group' }">{{ targetLabel(message) }}</b>
              <span v-if="message.to.kind === 'group'" class="gp-tag">{{ t("Group") }} · {{ recipients(message) }}</span>
              <span class="gp-via" :class="`via-${message.via}`">{{ t(message.via) }}</span>
              <time>{{ ago(message.ts) }}</time>
            </span>
            <span class="gp-text">{{ messagePreview(message, 120) }}</span>
          </span>
        </button>
      </li>
      <li v-if="!inReplay" class="gp-end" role="status">
        <template v-if="graph.loadingOlder">{{ t("Loading earlier messages…") }}</template>
        <button v-else-if="graph.olderFailed" class="gp-retry" @click="loadOlder()">{{ t("Could not load earlier messages. Retry") }}</button>
        <template v-else-if="!graph.more">{{ t("That is the start of the history.") }}</template>
      </li>
    </ol>
    <Teleport to="body">
      <div
        v-if="card"
        ref="cardEl"
        class="gp-card"
        :class="{ 'is-group': card.message.to.kind === 'group' }"
        :style="{ '--grp': groupColor(card.message) }"
        role="tooltip"
        @mouseenter="keep"
        @mouseleave="hide"
      >
        <div class="gp-card-head">
          <b>{{ senderLabel(card.message) }}</b><span class="gp-arrow">→</span><b>{{ targetLabel(card.message) }}</b>
          <span v-if="card.message.to.kind === 'group'" class="gp-tag">{{ t("Group") }}</span>
        </div>
        <div class="gp-card-row"><span>{{ t("Time") }}</span><span>{{ exact(card.message.ts) }}</span></div>
        <div class="gp-card-row"><span>{{ t("Via") }}</span><span>{{ t(card.message.via) }}</span></div>
        <div class="gp-card-row"><span>{{ t("Mode") }}</span><span>{{ t(card.message.mode) }} · {{ t(card.message.status) }}</span></div>
        <div v-if="card.message.hops" class="gp-card-row"><span>{{ t("Hops") }}</span><span>{{ card.message.hops }}</span></div>
        <div v-if="card.message.disposition" class="gp-card-row"><span>{{ t("Taken as") }}</span><span>{{ t(card.message.disposition) }}</span></div>
        <div v-if="card.message.recipients.length" class="gp-card-row"><span>{{ t("Reached") }}</span><span>{{ names(card.message) }}</span></div>
        <div class="gp-card-text">{{ tipText(card.message) }}</div>
      </div>
    </Teleport>
  </div>
</template>

<style>
.gp-card {
  position: fixed; left: 0; top: 0; z-index: 60; width: 340px; max-width: calc(100vw - 16px); padding: 11px 13px; border-radius: 12px;
  display: flex; flex-direction: column; gap: 5px; background: var(--graph-card); border: 1px solid var(--graph-card-border);
  box-shadow: var(--graph-shadow); -webkit-backdrop-filter: blur(14px); backdrop-filter: blur(14px); color: var(--text); font-size: 0.8rem;
}
.gp-card.is-group { border-color: var(--grp); }
.gp-card-head { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; font-size: 0.92rem; }
.gp-card-head b { font-weight: 650; overflow-wrap: anywhere; }
.gp-card-row { display: flex; justify-content: space-between; gap: 18px; }
.gp-card-row > span:first-child { color: var(--muted); flex: none; }
.gp-card-row > span:last-child { text-align: right; overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }
.gp-card-text { margin-top: 3px; padding: 7px 9px; border-radius: 8px; background: var(--hover); line-height: 1.42; white-space: pre-wrap; overflow-wrap: anywhere; max-height: 240px; overflow: auto; }
@media (hover: none) { .gp-card { display: none; } }
.gp { flex: 1; min-height: 0; display: flex; flex-direction: column; overflow: hidden; }
.gp-stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; padding: 4px 12px 10px; }
.gp-stats > div { display: flex; flex-direction: column; gap: 1px; padding: 8px 10px; border-radius: 12px; background: var(--surface-2); }
.gp-stats b { font-size: 1.25rem; font-weight: 650; font-variant-numeric: tabular-nums; letter-spacing: -0.01em; }
.gp-stats span { font-size: 0.72rem; color: var(--muted); }
.gp-legend { display: flex; flex-wrap: wrap; gap: 6px 14px; padding: 2px 16px 12px; border-bottom: 1px solid var(--divider); font-size: 0.75rem; color: var(--muted); }
.gp-key { display: inline-flex; align-items: center; gap: 6px; }
.gp-key i { display: inline-block; flex: none; }
.gp-key .sw { width: 14px; height: 4px; border-radius: 2px; }
.gp-key .ring { width: 11px; height: 11px; border-radius: 50%; border: 2px solid var(--muted); }
.gp-key .ring.idle { border-color: var(--ok); }
.gp-key .ring.working { border-color: var(--warn); animation: pulse 1.4s ease-in-out infinite; }
.gp-key .hull { width: 16px; height: 11px; border-radius: 6px; border: 1px dashed var(--accent); background: var(--accent-soft); }
.via-user { background: var(--via-user); }
.via-agent { background: var(--via-agent); }
.via-external { background: var(--via-external); }
.gp-head { display: flex; align-items: center; padding: 10px 12px 4px 16px; }
.gp-head h3 { flex: 1; margin: 0; font-size: 0.8rem; font-weight: 600; color: var(--accent); letter-spacing: 0.02em; }
.gp-replay { width: 30px; height: 30px; }
.gp-none { padding: 20px 16px; color: var(--muted); font-size: 0.85rem; line-height: 1.45; }
.gp-feed { list-style: none; margin: 0; padding: 0 6px 10px; overflow-y: auto; overscroll-behavior: contain; flex: 1; min-height: 0; }
.gp-item { display: flex; align-items: flex-start; gap: 10px; width: 100%; padding: 9px 10px; border-radius: 12px; text-align: left; animation: fade 0.25s ease-out; }
.gp-item:hover { background: var(--hover); }
.gp-item.is-group { background: color-mix(in srgb, var(--grp) 9%, transparent); box-shadow: inset 3px 0 0 var(--grp); border-radius: 4px 12px 12px 4px; }
.gp-item.is-group:hover { background: color-mix(in srgb, var(--grp) 16%, transparent); }
.gp-hash { display: grid; place-items: center; border-radius: 8px; background: var(--grp); color: #fff; font-weight: 700; font-size: 0.9rem; line-height: 1; }
.gp-line b.grp { color: var(--grp); }
.gp-tag { flex: none; padding: 0 6px; border-radius: 6px; font-size: 0.64rem; font-weight: 700; line-height: 1.5; color: var(--grp); border: 1px solid var(--grp); letter-spacing: 0.02em; }
.gp-end { padding: 10px 12px 14px; text-align: center; font-size: 0.74rem; color: var(--muted); }
.gp-retry { color: var(--accent); font-size: 0.74rem; }
.gp-av { flex: none; width: 26px; height: 26px; border-radius: 50%; margin-top: 1px; }
.gp-body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.gp-line { display: flex; align-items: baseline; gap: 5px; font-size: 0.82rem; min-width: 0; }
.gp-line b { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
.gp-line b.grp { color: var(--accent); }
.gp-arrow { color: var(--muted); flex: none; }
.gp-via { flex: none; padding: 0 6px; border-radius: 999px; font-size: 0.64rem; font-weight: 600; line-height: 1.5; color: #fff; }
.gp-line time { margin-left: auto; flex: none; font-size: 0.7rem; color: var(--muted); font-variant-numeric: tabular-nums; }
.gp-text { font-size: 0.78rem; color: var(--muted); overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow-wrap: anywhere; }
@media (prefers-reduced-motion: reduce) {
  .gp-item, .gp-key .ring.working { animation: none; }
}
</style>
