<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";

import { drawingSize, fitScale, fitted, percent, STEP, zoomAt, type View } from "../../core/zoom.js";
import { closeLightbox, state } from "../store.js";
import Icon from "./Icon.vue";

const stage = ref<HTMLElement | null>(null);
const dialog = ref<HTMLElement | null>(null);
const view = ref<View>({ scale: 1, x: 0, y: 0 });
/** The content's own size in pixels: a picture's pixels, or the size a drawing declares. */
const natural = ref<{ width: number; height: number } | null>(null);
const dragging = ref(false);
/** Whether the pointer moved while it was down, so the click that ends a drag does not close the box. */
let moved = false;
let origin = { x: 0, y: 0, px: 0, py: 0 };

const shown = computed(() => state.lightbox);
const zooms = computed(() => shown.value?.kind === "image" || shown.value?.kind === "drawing");

/** A drawing keeps its sharpness, so it is allowed to grow to fill the box; a picture is not stretched past its pixels. */
function cap(): number {
  return shown.value?.kind === "drawing" ? 4 : 1;
}

function fit(): void {
  const box = stage.value;
  if (box === null || natural.value === null) {
    return;
  }
  view.value = fitted(fitScale(natural.value.width, natural.value.height, box.clientWidth, box.clientHeight, cap()));
}

function measure(): void {
  const current = shown.value;
  natural.value = null;
  if (current?.kind === "drawing") {
    natural.value = drawingSize(current.html) ?? { width: 800, height: 600 };
    void nextTick(fit);
  }
  // A picture reports its size when it has loaded (see `loaded`).
}

function loaded(event: Event): void {
  const image = event.target as HTMLImageElement;
  natural.value = { width: image.naturalWidth || 800, height: image.naturalHeight || 600 };
  void nextTick(fit);
}

function zoomBy(factor: number, px = 0, py = 0): void {
  view.value = zoomAt(view.value, factor, px, py);
}

/** The pointer's distance from the centre of the stage, which is where the content's offset is measured from. */
function fromCentre(event: { clientX: number; clientY: number }): { px: number; py: number } {
  const rect = stage.value?.getBoundingClientRect();
  if (rect === undefined) {
    return { px: 0, py: 0 };
  }
  return { px: event.clientX - (rect.left + rect.width / 2), py: event.clientY - (rect.top + rect.height / 2) };
}

function onWheel(event: WheelEvent): void {
  if (!zooms.value) {
    return;
  }
  const { px, py } = fromCentre(event);
  zoomBy(event.deltaY < 0 ? STEP : 1 / STEP, px, py);
}

function onDown(event: PointerEvent): void {
  if (!zooms.value || event.button !== 0) {
    return;
  }
  moved = false;
  dragging.value = true;
  origin = { x: view.value.x, y: view.value.y, px: event.clientX, py: event.clientY };
  (event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId);
}

function onMove(event: PointerEvent): void {
  if (!dragging.value) {
    return;
  }
  const dx = event.clientX - origin.px;
  const dy = event.clientY - origin.py;
  if (Math.abs(dx) + Math.abs(dy) > 3) {
    moved = true;
  }
  view.value = { ...view.value, x: origin.x + dx, y: origin.y + dy };
}

function onUp(): void {
  dragging.value = false;
}

/** A click on the dark around the content closes the box; one that ended a drag, or landed on the content, does not. */
function onBackdrop(event: MouseEvent): void {
  if (moved) {
    moved = false;
    return;
  }
  const target = event.target as HTMLElement;
  if (target === stage.value || target.classList.contains("lb-doc-wrap")) {
    closeLightbox();
  }
}

/** Double-click: from fitted to the real size, and back. */
function onDouble(event: MouseEvent): void {
  if (!zooms.value || natural.value === null) {
    return;
  }
  const box = stage.value;
  const wanted = fitScale(natural.value.width, natural.value.height, box?.clientWidth ?? 0, box?.clientHeight ?? 0, cap());
  if (Math.abs(view.value.scale - wanted) < 0.01) {
    const { px, py } = fromCentre(event);
    view.value = zoomAt(view.value, 1 / view.value.scale, px, py);
  } else {
    fit();
  }
}

/** Keys belong to the box while it is open: Escape must close it and not stop the request running behind it. */
function onKey(event: KeyboardEvent): void {
  if (shown.value === null) {
    return;
  }
  if (event.key === "Escape") {
    event.preventDefault();
    event.stopPropagation();
    closeLightbox();
  } else if (zooms.value && (event.key === "+" || event.key === "=")) {
    event.preventDefault();
    zoomBy(STEP);
  } else if (zooms.value && (event.key === "-" || event.key === "_")) {
    event.preventDefault();
    zoomBy(1 / STEP);
  } else if (zooms.value && event.key === "0") {
    event.preventDefault();
    fit();
  }
}

watch(shown, (current) => {
  if (current !== null) {
    measure();
    void nextTick(() => dialog.value?.focus());
  }
});

const onResize = (): void => {
  if (zooms.value) {
    fit();
  }
};

onMounted(() => {
  window.addEventListener("keydown", onKey, true);
  window.addEventListener("resize", onResize);
  if (shown.value !== null) {
    measure();
    void nextTick(() => dialog.value?.focus());
  }
});
onBeforeUnmount(() => {
  window.removeEventListener("keydown", onKey, true);
  window.removeEventListener("resize", onResize);
});

const placed = computed(() => ({
  width: natural.value ? `${natural.value.width}px` : undefined,
  height: natural.value ? `${natural.value.height}px` : undefined,
  transform: `translate(calc(-50% + ${view.value.x}px), calc(-50% + ${view.value.y}px)) scale(${view.value.scale})`,
}));
</script>

<template>
  <div v-if="shown" id="lightbox" ref="dialog" class="lightbox" role="dialog" aria-modal="true" :aria-label="shown.title" tabindex="-1">
    <div class="lb-bar">
      <span class="lb-title">{{ shown.title }}</span>
      <template v-if="zooms">
        <button class="icon-btn" type="button" title="Zoom out (−)" aria-label="Zoom out" @click="zoomBy(1 / STEP)"><Icon name="minus" /></button>
        <span class="lb-zoom" title="Zoom">{{ percent(view.scale) }}</span>
        <button class="icon-btn" type="button" title="Zoom in (+)" aria-label="Zoom in" @click="zoomBy(STEP)"><Icon name="plus" /></button>
        <button class="icon-btn" type="button" title="Fit to the window (0)" aria-label="Fit to the window" @click="fit"><Icon name="fit" /></button>
      </template>
      <button class="icon-btn lb-close" type="button" title="Close (Esc)" aria-label="Close" @click="closeLightbox"><Icon name="x" /></button>
    </div>

    <div
      v-if="zooms"
      ref="stage"
      class="lb-stage"
      :class="{ grabbing: dragging }"
      @wheel.prevent="onWheel"
      @pointerdown="onDown"
      @pointermove="onMove"
      @pointerup="onUp"
      @pointercancel="onUp"
      @click="onBackdrop"
      @dblclick="onDouble"
    >
      <img v-if="shown.kind === 'image'" class="lb-content lb-image" :src="shown.src" alt="" draggable="false" :style="placed" @load="loaded" />
      <div v-else-if="shown.kind === 'drawing'" class="lb-content lb-drawing" :style="placed" v-html="shown.html" />
    </div>

    <div v-else class="lb-doc-wrap" @click="onBackdrop">
      <div class="lb-doc md" v-html="shown.kind === 'block' ? shown.html : ''" />
    </div>
  </div>
</template>

<style>
.lightbox {
  position: absolute;
  inset: 0;
  z-index: 200;
  display: flex;
  flex-direction: column;
  background: color-mix(in srgb, var(--bg) 88%, black);
  outline: none;
  animation: lightbox-fade 0.12s ease-out;
}

@keyframes lightbox-fade {
  from {
    opacity: 0;
  }
}

.lb-bar {
  position: relative;
  z-index: 2;
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--line);
  background: color-mix(in srgb, var(--bg) 70%, transparent);
}

.lb-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  color: var(--muted);
  font-size: var(--small);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.lb-zoom {
  min-width: 3.6em;
  color: var(--muted);
  font-size: var(--small);
  font-variant-numeric: tabular-nums;
  text-align: center;
}

.lb-close {
  margin-left: 8px;
}

.lb-stage {
  position: relative;
  flex: 1;
  overflow: hidden;
  cursor: grab;
  touch-action: none;
  user-select: none;
}

.lb-stage.grabbing {
  cursor: grabbing;
}

/* Content sits at the middle of the stage; its own transform (translate, then scale) moves it from there. */
.lb-content {
  position: absolute;
  left: 50%;
  top: 50%;
  max-width: none;
  transform-origin: center center;
}

.lb-image {
  box-shadow: var(--shadow);
}

.lb-drawing {
  padding: 0;
}

.lb-drawing svg {
  display: block;
  width: 100%;
  height: 100%;
  max-width: none !important;
}

.lb-doc-wrap {
  flex: 1;
  overflow: auto;
  padding: 20px;
}

.lb-doc {
  width: min(1200px, 100%);
  margin: 0 auto;
}

.lb-doc .code-block,
.lb-doc .table-wrap {
  margin: 0;
}

.lb-doc .table-wrap {
  overflow-x: auto;
}

.lb-doc table {
  font-size: 1em;
}
</style>
