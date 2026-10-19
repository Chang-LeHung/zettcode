<script setup lang="ts">
import { computed, ref, watch } from "vue";

import { formatTokens } from "../../core/format.js";
import { formatPercent } from "../context.js";
import { post, state } from "../store.js";

const props = defineProps<{ window: number; usedPercent: number | null }>();

const STEP = 5;
const MIN = 5;
const MAX = 100;

const saved = computed(() => Math.round(state.ui?.settings?.model.compact_percent ?? 80));
const draft = ref(saved.value);
const rail = ref<HTMLElement | null>(null);
const dragging = ref(false);

watch(saved, (value) => {
  draft.value = value;
});

const changed = computed(() => draft.value !== saved.value);
const tokens = computed(() => Math.round((props.window * draft.value) / 100));
const busy = computed(() => state.ui?.busy === true);

function snap(value: number): number {
  return Math.min(MAX, Math.max(MIN, Math.round(value / STEP) * STEP));
}

function fromPointer(event: PointerEvent): void {
  const element = rail.value;
  if (element === null) {
    return;
  }
  const box = element.getBoundingClientRect();
  if (box.width > 0) {
    draft.value = snap(((event.clientX - box.left) / box.width) * 100);
  }
}

function down(event: PointerEvent): void {
  if (busy.value) {
    return;
  }
  dragging.value = true;
  (event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId);
  fromPointer(event);
}

function move(event: PointerEvent): void {
  if (dragging.value) {
    fromPointer(event);
  }
}

function up(): void {
  dragging.value = false;
}

function apply(): void {
  if (changed.value && !busy.value) {
    post({ type: "set-compact", percent: draft.value });
  }
}

function key(event: KeyboardEvent): void {
  const moves: Record<string, number> = { ArrowLeft: -STEP, ArrowDown: -STEP, ArrowRight: STEP, ArrowUp: STEP };
  if (event.key in moves) {
    event.preventDefault();
    draft.value = snap(draft.value + (moves[event.key] ?? 0));
  } else if (event.key === "Home") {
    event.preventDefault();
    draft.value = MIN;
  } else if (event.key === "End") {
    event.preventDefault();
    draft.value = MAX;
  } else if (event.key === "Enter") {
    event.preventDefault();
    event.stopPropagation();
    apply();
  } else if (event.key === "Escape" && changed.value) {
    event.stopPropagation();
    draft.value = saved.value;
  }
}
</script>

<template>
  <div id="compaction" class="compaction">
    <div class="compaction-head">
      <span class="compaction-title">Compaction point</span>
      <span class="compaction-value"
        ><strong>{{ draft }}%</strong><span class="muted"> · {{ formatTokens(tokens) }} tokens</span></span
      >
    </div>

    <div
      ref="rail"
      class="rail-slider"
      :class="{ dragging, disabled: busy }"
      role="slider"
      tabindex="0"
      aria-label="Compaction point"
      :aria-valuemin="MIN"
      :aria-valuemax="MAX"
      :aria-valuenow="draft"
      :aria-valuetext="`${draft} percent of the window`"
      @pointerdown="down"
      @pointermove="move"
      @pointerup="up"
      @pointercancel="up"
      @keydown="key"
    >
      <div class="slider-track">
        <div class="slider-fill" :style="{ width: `${draft}%` }" />
        <i v-for="mark in [25, 50, 75]" :key="mark" class="slider-mark" :style="{ left: `${mark}%` }" />
        <i
          v-if="usedPercent !== null"
          class="slider-used"
          :class="{ over: usedPercent >= draft }"
          :style="{ left: `${Math.min(100, usedPercent)}%` }"
          :title="`In use now: ${formatPercent(usedPercent)}%`"
        />
      </div>
      <div class="slider-knob" :style="{ left: `${draft}%` }" />
    </div>

    <div class="compaction-foot">
      <span v-if="busy" class="muted">Available when the run ends</span>
      <span v-else-if="changed" class="muted">Enter to apply · Esc to undo</span>
      <span v-else class="muted">Click or use ← → in steps of {{ STEP }}%</span>
      <button class="btn small" :class="{ solid: changed }" type="button" :disabled="!changed || busy" @click="apply">Apply</button>
    </div>
  </div>
</template>

<style>
.compaction {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--line);
}

.compaction-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  font-size: var(--small);
}

.compaction-title {
  font-weight: 600;
}

.compaction-value strong {
  font-variant-numeric: tabular-nums;
}

.rail-slider {
  position: relative;
  height: 26px;
  margin: 4px 8px 0;
  cursor: pointer;
  touch-action: none;
  outline: none;
}

.rail-slider.disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.slider-track {
  position: absolute;
  left: 0;
  right: 0;
  top: 11px;
  height: 4px;
  border-radius: 2px;
  background: var(--wash-2);
}

.slider-fill {
  height: 100%;
  border-radius: 2px;
  background: var(--brand);
}

.rail-slider.dragging .slider-fill {
  transition: none;
}

.slider-fill {
  transition: width 0.12s ease-out;
}

.slider-mark {
  position: absolute;
  top: -2px;
  width: 1px;
  height: 8px;
  background: var(--line-strong);
}

/* Where the conversation stands now: the knob has to sit past it before a compaction can be due. */
.slider-used {
  position: absolute;
  top: -5px;
  width: 2px;
  height: 14px;
  margin-left: -1px;
  border-radius: 1px;
  background: var(--muted);
}

.slider-used.over {
  background: var(--amber);
}

.slider-knob {
  position: absolute;
  top: 5px;
  width: 16px;
  height: 16px;
  margin-left: -8px;
  border-radius: 50%;
  background: var(--fg);
  box-shadow:
    0 0 0 3px color-mix(in srgb, var(--accent) 30%, transparent),
    0 1px 4px rgba(0, 0, 0, 0.45);
  transition: left 0.12s ease-out, box-shadow 0.12s;
}

.rail-slider.dragging .slider-knob {
  transition: none;
  box-shadow:
    0 0 0 6px color-mix(in srgb, var(--accent) 35%, transparent),
    0 1px 4px rgba(0, 0, 0, 0.45);
}

.rail-slider:focus-visible .slider-knob {
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--accent) 55%, transparent);
}

.compaction-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-top: 2px;
  font-size: 11px;
}
</style>
