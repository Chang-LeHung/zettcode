<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";

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

/** One entry for each message the reader sent: not a side question, a command's row or a change announcement. */
const items = computed(() =>
  state.turns
    .filter((turn) => !turn.aside && !isAnnouncement(turn) && (turn.prompt.trim() !== "" || turn.images.length > 0 || Boolean(turn.imageCount)))
    .map((turn) => ({ id: turn.id, text: turn.prompt.trim() || "(image)" })),
);

const shown = computed(() => items.value.length >= 2);

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
  const calm = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;
  target.scrollIntoView({ block: "start", behavior: calm ? "auto" : "smooth" });
  active.value = index;
  flash(item.id);
}

function onClick(event: MouseEvent): void {
  const centre = centres();
  if (centre.length > 0) {
    go(nearest(centre, event.clientY));
  }
}

function onKey(event: KeyboardEvent): void {
  if (event.key === "ArrowUp" || event.key === "ArrowLeft") {
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

onBeforeUnmount(() => {
  props.scroller?.removeEventListener("scroll", schedule);
  window.cancelAnimationFrame(frame);
});
</script>

<template>
  <nav
    v-if="shown"
    ref="rail"
    class="rail-nav"
    :class="{ hot: hovered !== null }"
    aria-label="Jump to one of your messages"
    tabindex="0"
    :style="{ '--count': items.length }"
    @pointermove="onMove"
    @pointerleave="onLeave"
    @click="onClick"
    @keydown="onKey"
  >
    <i
      v-for="(item, index) in items"
      :key="item.id"
      class="rail-tick"
      :class="{ active: index === active, hover: index === hovered }"
      :style="{ '--k': levels[index] ?? 0 }"
    />
    <div v-if="hovered !== null && items[hovered]" class="rail-tip" :style="{ top: `${tipTop}px` }">
      <span class="rail-tip-count">{{ hovered + 1 }} / {{ items.length }}</span>
      <span class="rail-tip-text">{{ items[hovered]!.text }}</span>
    </div>
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
