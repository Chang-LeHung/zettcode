<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";

import { GROUP, isDense, popupTop, unitsOf } from "../../core/rail.js";
import { isAnnouncement } from "../../core/state.js";
import { flash, state } from "../store.js";

const props = defineProps<{ scroller: HTMLElement | null }>();

/** How far, in pixels, a hovered tick's neighbours still lean toward the pointer: the width of the swell. */
const SWELL = 26;

const rail = ref<HTMLElement | null>(null);
const hovered = ref<number | null>(null);
const levels = ref<number[]>([]);
const tipTop = ref(0);
const active = ref(0);
/** The height of the view the rail lies in; the bars group themselves when it cannot hold one for each message. */
const viewport = ref(0);
/** The group whose messages are listed beside the rail, when the bars are groups. */
const opened = ref<number | null>(null);
const popup = ref<{ left: number; top: number } | null>(null);

/** One entry for each message the reader sent: not a side question, a command's row or a change announcement. */
const items = computed(() =>
  state.turns
    .filter((turn) => !turn.aside && !isAnnouncement(turn) && (turn.prompt.trim() !== "" || turn.images.length > 0 || Boolean(turn.imageCount)))
    .map((turn) => ({ id: turn.id, text: turn.prompt.trim() || "(image)" })),
);

const shown = computed(() => items.value.length >= 2);

/** Ten messages to a bar when one bar for each would be too close to aim at; a bar for each message otherwise. */
const dense = computed(() => isDense(items.value.length, viewport.value));
const units = computed(() => unitsOf(items.value.length, dense.value));

function unitOf(index: number): number {
  return dense.value ? Math.floor(index / GROUP) : index;
}

/** The messages of the opened group: the second level, where one is picked. */
const listed = computed(() => {
  const unit = opened.value === null ? undefined : units.value[opened.value];
  return unit === undefined ? [] : items.value.slice(unit.first, unit.last + 1).map((item, offset) => ({ ...item, index: unit.first + offset }));
});

function label(unit: number): string {
  const span = units.value[unit];
  if (span === undefined) {
    return "";
  }
  return span.first === span.last ? `${span.first + 1}` : `${span.first + 1}–${span.last + 1}`;
}

function close(): void {
  opened.value = null;
  popup.value = null;
}

/** List a group's messages beside its bar, where the reader picks one. */
function openGroup(unit: number, centre: number): void {
  const box = rail.value?.getBoundingClientRect();
  const span = units.value[unit];
  if (span === undefined) {
    return;
  }
  const rows = span.last - span.first + 1;
  const height = Math.min(rows * 30 + 34, window.innerHeight - 16);
  opened.value = unit;
  popup.value = { left: (box?.right ?? 0) + 8, top: popupTop(centre, height, window.innerHeight) };
}

function ticks(): HTMLElement[] {
  return Array.from(rail.value?.querySelectorAll<HTMLElement>(".rail-tick") ?? []);
}

/** The vertical middle of every tick, on the screen. */
function centres(): number[] {
  return ticks().map((tick) => {
    const box = tick.getBoundingClientRect();
    return box.top + box.height / 2;
  });
}

function nearest(centre: number[], y: number): number {
  let best = 0;
  let distance = Infinity;
  centre.forEach((value, index) => {
    const gap = Math.abs(value - y);
    if (gap < distance) {
      distance = gap;
      best = index;
    }
  });
  return best;
}

function onMove(event: MouseEvent): void {
  const centre = centres();
  if (centre.length === 0) {
    return;
  }
  const y = event.clientY;
  const index = nearest(centre, y);
  hovered.value = index;
  // The ticks swell like a dock's icons: the one under the pointer most, its neighbours less, the rest not at all.
  levels.value = centre.map((value) => Math.exp(-(((value - y) / SWELL) ** 2)));
  tipTop.value = (centre[index] ?? 0) - (rail.value?.getBoundingClientRect().top ?? 0);
}

function onLeave(): void {
  hovered.value = null;
  levels.value = [];
}

/** Scroll to a message, and flash it so the eye finds where it landed. */
function go(index: number): void {
  const item = items.value[index];
  const container = props.scroller;
  if (item === undefined || container === null) {
    return;
  }
  const target = container.querySelector<HTMLElement>(`[data-id="${item.id}"]`);
  if (target === null) {
    return;
  }
  close();
  const calm = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;
  target.scrollIntoView({ block: "start", behavior: calm ? "auto" : "smooth" });
  active.value = index;
  flash(item.id);
}

function onClick(event: MouseEvent): void {
  const centre = centres();
  if (centre.length === 0) {
    return;
  }
  const unit = nearest(centre, event.clientY);
  if (dense.value) {
    // A bar that stands for ten messages opens the list of them; the message is picked there.
    if (opened.value === unit) {
      close();
    } else {
      openGroup(unit, centre[unit] ?? event.clientY);
    }
    return;
  }
  go(unit);
}

function onOutside(event: Event): void {
  const inside = event.target instanceof Element && event.target.closest(".rail-pick") !== null;
  if (opened.value !== null && !inside && !rail.value?.contains(event.target as Node)) {
    close();
  }
}

/** A list that no longer matches the bars (the view was resized, a message was sent) is closed rather than left stale. */
watch([dense, () => items.value.length], close);

function onKey(event: KeyboardEvent): void {
  if (event.key === "Escape" && opened.value !== null) {
    event.preventDefault();
    close();
  } else if (event.key === "ArrowUp" || event.key === "ArrowLeft") {
    event.preventDefault();
    go(Math.max(0, active.value - 1));
  } else if (event.key === "ArrowDown" || event.key === "ArrowRight") {
    event.preventDefault();
    go(Math.min(items.value.length - 1, active.value + 1));
  } else if (event.key === "Home") {
    event.preventDefault();
    go(0);
  } else if (event.key === "End") {
    event.preventDefault();
    go(items.value.length - 1);
  }
}

/** The message the reader is at: the last one that has reached the upper part of the view. */
function measure(): void {
  const container = props.scroller;
  if (container === null || items.value.length === 0) {
    return;
  }
  viewport.value = container.clientHeight;
  const top = container.getBoundingClientRect().top;
  const line = top + Math.min(160, container.clientHeight * 0.35);
  let found = 0;
  items.value.forEach((item, index) => {
    const element = container.querySelector<HTMLElement>(`[data-id="${item.id}"]`);
    if (element !== null && element.getBoundingClientRect().top <= line) {
      found = index;
    }
  });
  active.value = found;
}

let frame = 0;
function schedule(): void {
  if (frame === 0) {
    frame = window.requestAnimationFrame(() => {
      frame = 0;
      measure();
    });
  }
}

watch(
  () => props.scroller,
  (element, previous) => {
    previous?.removeEventListener("scroll", schedule);
    element?.addEventListener("scroll", schedule, { passive: true });
    schedule();
  },
  { immediate: true },
);

watch(
  () => [items.value.length, state.tick],
  async () => {
    await nextTick();
    schedule();
  },
);

window.addEventListener("resize", schedule);
document.addEventListener("pointerdown", onOutside, true);

onBeforeUnmount(() => {
  window.removeEventListener("resize", schedule);
  document.removeEventListener("pointerdown", onOutside, true);
  props.scroller?.removeEventListener("scroll", schedule);
  window.cancelAnimationFrame(frame);
});
</script>

<template>
  <nav
    v-if="shown"
    ref="rail"
    class="rail-nav"
    :class="{ hot: hovered !== null, dense }"
    aria-label="Jump to one of your messages"
    tabindex="0"
    :style="{ '--count': units.length }"
    @pointermove="onMove"
    @pointerleave="onLeave"
    @click="onClick"
    @keydown="onKey"
  >
    <i
      v-for="(unit, index) in units"
      :key="unit.first"
      class="rail-tick"
      :class="{
        active: active >= unit.first && active <= unit.last,
        hover: index === hovered,
        group: unit.first !== unit.last,
        opened: index === opened,
      }"
      :style="{ '--k': levels[index] ?? 0 }"
    />
    <div v-if="hovered !== null && units[hovered] && items[units[hovered]!.first] && hovered !== opened" class="rail-tip" :style="{ top: `${tipTop}px` }">
      <span class="rail-tip-count">{{ label(hovered) }} / {{ items.length }}</span>
      <span class="rail-tip-text">{{ items[units[hovered]!.first]!.text }}</span>
      <span v-if="units[hovered]!.first !== units[hovered]!.last" class="rail-tip-more">Click to choose one of these {{ units[hovered]!.last - units[hovered]!.first + 1 }}</span>
    </div>
    <!-- The second level: when one bar stands for ten messages, they are listed here and one is picked. It is drawn
         at the body because the rail is moved with a transform, which would turn `fixed` into "fixed to the rail". -->
    <Teleport to="body">
    <div
      v-if="opened !== null && popup"
      class="rail-pick"
      role="listbox"
      :aria-label="`Messages ${label(opened)}`"
      :style="{ left: `${popup.left}px`, top: `${popup.top}px` }"
    >
      <div class="rail-pick-head">{{ label(opened) }} / {{ items.length }}</div>
      <button
        v-for="row in listed"
        :key="row.id"
        class="rail-pick-row"
        :class="{ current: row.index === active }"
        type="button"
        role="option"
        :aria-selected="row.index === active"
        @click="go(row.index)"
      >
        <span class="rail-pick-n">{{ row.index + 1 }}</span>
        <span class="rail-pick-text">{{ row.text }}</span>
      </button>
    </div>
    </Teleport>
  </nav>
</template>

<style>
/* A column of short bars along the left edge, one for each message you sent. */
.rail-nav {
  position: absolute;
  left: 2px;
  top: 50%;
  z-index: 6;
  width: 16px;
  height: min(calc(var(--count) * 11px), 72%);
  min-height: 28px;
  padding: 4px 0;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  align-items: flex-start;
  transform: translateY(-50%);
  cursor: pointer;
  outline: none;
}

.rail-nav:focus-visible {
  border-radius: 4px;
  box-shadow: 0 0 0 1px var(--accent);
}

.rail-tick {
  display: block;
  flex: 0 0 auto;
  width: calc(6px + 10px * var(--k, 0));
  height: calc(2px + 1.5px * var(--k, 0));
  border-radius: 2px;
  background: var(--fg);
  opacity: calc(0.28 + 0.62 * var(--k, 0));
  pointer-events: none;
  transition:
    width 0.12s ease-out,
    height 0.12s ease-out,
    opacity 0.12s ease-out;
}

.rail-tick.active {
  width: calc(10px + 6px * var(--k, 0));
  background: var(--accent);
  opacity: 1;
}

.rail-tick.hover {
  background: var(--fg);
}

/* A bar that stands for ten messages is longer, so it reads as a group and not as one message. */
.rail-tick.group {
  width: calc(10px + 8px * var(--k, 0));
  height: calc(2px + 1px * var(--k, 0));
}

.rail-tick.group.active {
  width: calc(14px + 6px * var(--k, 0));
}

.rail-tick.opened {
  background: var(--accent);
  opacity: 1;
}

.rail-tick.hover.active {
  background: var(--accent);
}

.rail-tip {
  position: absolute;
  left: 24px;
  width: max-content;
  max-width: 240px;
  padding: 6px 10px;
  transform: translateY(-50%);
  border: 1px solid var(--line-strong);
  border-radius: var(--r-m);
  background: var(--raised);
  box-shadow: var(--shadow);
  font-size: var(--small);
  line-height: 1.45;
  pointer-events: none;
  animation: rise 0.12s ease-out;
}

.rail-tip-more {
  display: block;
  margin-top: 3px;
  color: var(--faint);
  font-size: var(--tiny);
}

.rail-pick {
  position: fixed;
  z-index: 80;
  width: min(320px, calc(100vw - 48px));
  max-height: calc(100vh - 16px);
  overflow-y: auto;
  padding: 6px;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-m);
  background: var(--raised);
  box-shadow: var(--shadow);
  cursor: default;
  animation: rise 0.12s ease-out;
}

.rail-pick-head {
  padding: 2px 8px 6px;
  color: var(--faint);
  font-size: var(--tiny);
  font-variant-numeric: tabular-nums;
}

.rail-pick-row {
  display: flex;
  align-items: baseline;
  gap: 8px;
  width: 100%;
  padding: 5px 8px;
  border: 0;
  border-radius: 6px;
  background: none;
  color: var(--fg);
  font-size: var(--small);
  text-align: left;
}

.rail-pick-row:hover,
.rail-pick-row:focus-visible {
  background: var(--wash-2);
  outline: none;
}

.rail-pick-row.current .rail-pick-n {
  color: var(--accent);
}

.rail-pick-n {
  flex: 0 0 2.4em;
  color: var(--faint);
  font-variant-numeric: tabular-nums;
  text-align: right;
}

.rail-pick-text {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rail-tip-count {
  display: block;
  margin-bottom: 2px;
  color: var(--faint);
  font-size: var(--tiny);
  font-variant-numeric: tabular-nums;
}

.rail-tip-text {
  display: -webkit-box;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}
</style>
