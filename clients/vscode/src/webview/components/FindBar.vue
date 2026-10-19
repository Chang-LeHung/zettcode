<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";

import { findHits, findLabel, stepIndex, type Hit } from "../../core/find.js";
import { closeFind, state } from "../store.js";
import Icon from "./Icon.vue";

/** The colours are the `::highlight()` rules below; where the page has no such thing, the count and the jump remain. */
interface HighlightRegistry {
  set(name: string, value: unknown): void;
  delete(name: string): void;
}
const registry = (): HighlightRegistry | null => {
  const css = (window as unknown as { CSS?: { highlights?: HighlightRegistry } }).CSS;
  return css?.highlights ?? null;
};

const input = ref<HTMLInputElement | null>(null);
let hits: Hit[] = [];
let timer: number | undefined;

const label = computed(() => findLabel(state.find.query, state.find.index, state.find.count));

function rangeOf(hit: Hit): Range {
  const range = document.createRange();
  range.setStart(hit.node, hit.start);
  range.setEnd(hit.node, hit.end);
  return range;
}

/** Where a range ends on screen; a page that cannot measure it (a test's) puts everything at the top. */
function bottomOf(range: Range): number {
  return typeof range.getBoundingClientRect === "function" ? range.getBoundingClientRect().bottom : 0;
}

function paint(): void {
  const colours = registry();
  const Highlight = (window as unknown as { Highlight?: new (...ranges: Range[]) => unknown }).Highlight;
  if (colours === null || Highlight === undefined) {
    return;
  }
  colours.delete("zc-find");
  colours.delete("zc-find-current");
  if (!state.find.open || hits.length === 0) {
    return;
  }
  colours.set("zc-find", new Highlight(...hits.map(rangeOf)));
  const current = hits[state.find.index];
  if (current !== undefined) {
    colours.set("zc-find-current", new Highlight(rangeOf(current)));
  }
}

function reveal(): void {
  const current = hits[state.find.index];
  current?.node.parentElement?.scrollIntoView({ block: "center", behavior: "auto" });
}

/** Look again in what is on show. `fromTop` starts at the first hit the reader can see, as a find box in an editor does. */
function search(fromTop: boolean): void {
  const root = document.getElementById("turns");
  hits = state.find.open && root !== null ? findHits(root, state.find.query) : [];
  state.find.count = hits.length;
  if (fromTop) {
    const scroller = document.getElementById("transcript");
    const top = scroller?.getBoundingClientRect().top ?? 0;
    const seen = hits.findIndex((hit) => bottomOf(rangeOf(hit)) >= top);
    state.find.index = Math.max(0, seen);
    paint();
    reveal();
    return;
  }
  state.find.index = Math.min(state.find.index, Math.max(0, hits.length - 1));
  paint();
}

function step(by: number): void {
  if (hits.length === 0) {
    return;
  }
  state.find.index = stepIndex(state.find.index, hits.length, by);
  paint();
  reveal();
}

function onKey(event: KeyboardEvent): void {
  if (event.key === "Escape") {
    event.preventDefault();
    event.stopPropagation();
    closeFind();
  } else if (event.key === "Enter" && !event.isComposing) {
    event.preventDefault();
    step(event.shiftKey ? -1 : 1);
  } else if (event.key === "F3") {
    event.preventDefault();
    step(event.shiftKey ? -1 : 1);
  }
}

watch(
  () => state.find.query,
  () => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => search(true), 60);
  },
);

/** The conversation changes under an open search (a streaming answer, a request folded): the hits are found again, in place. */
watch(
  () => [state.tick, state.turns.length, state.collapsed.size],
  async () => {
    if (!state.find.open) {
      return;
    }
    await nextTick();
    window.clearTimeout(timer);
    timer = window.setTimeout(() => search(false), 120);
  },
);

watch(
  () => state.find.open,
  (open) => {
    if (open) {
      void nextTick().then(() => search(true));
    } else {
      hits = [];
      paint();
    }
  },
);

watch(
  () => state.find.focus,
  async () => {
    await nextTick();
    input.value?.focus();
    input.value?.select();
  },
);

onBeforeUnmount(() => {
  window.clearTimeout(timer);
  hits = [];
  paint();
});
</script>

<template>
  <div v-if="state.find.open" id="find" class="find" role="search">
    <input
      ref="input"
      v-model="state.find.query"
      class="find-input"
      type="text"
      placeholder="Find in conversation"
      aria-label="Find in conversation"
      spellcheck="false"
      autocomplete="off"
      @keydown="onKey"
    />
    <span class="find-count" :class="{ none: label === 'No results' }" aria-live="polite">{{ label }}</span>
    <button class="icon-btn find-btn" type="button" title="Previous match (Shift+Enter)" aria-label="Previous match" :disabled="state.find.count === 0" @click="step(-1)">
      <Icon name="up" :size="13" />
    </button>
    <button class="icon-btn find-btn" type="button" title="Next match (Enter)" aria-label="Next match" :disabled="state.find.count === 0" @click="step(1)">
      <Icon name="down" :size="13" />
    </button>
    <button class="icon-btn find-btn" type="button" title="Close (Esc)" aria-label="Close search" @click="closeFind">
      <Icon name="x" :size="13" />
    </button>
  </div>
</template>

<style>
.find {
  position: absolute;
  top: 8px;
  right: calc(var(--gutter) + 8px);
  z-index: 40;
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 4px 4px 4px 10px;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-m);
  background: var(--raised);
  box-shadow: var(--shadow);
  animation: rise 0.14s ease-out;
}

.find-input {
  width: 190px;
  min-width: 0;
  padding: 3px 0;
  border: 0;
  outline: 0;
  background: none;
  color: var(--fg);
  font: inherit;
  font-size: var(--small);
}

.find-count {
  min-width: 56px;
  padding: 0 6px;
  color: var(--muted);
  font-size: var(--tiny);
  text-align: right;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.find-count.none {
  color: var(--red);
}

.find-btn:disabled {
  opacity: 0.35;
}

/* The CSS Custom Highlight API paints the matches without touching the text: every hit, and the one the reader is on. */
::highlight(zc-find) {
  background-color: color-mix(in srgb, var(--amber) 35%, transparent);
  color: inherit;
}

::highlight(zc-find-current) {
  background-color: var(--amber);
  color: #1e1e1e;
}
</style>
