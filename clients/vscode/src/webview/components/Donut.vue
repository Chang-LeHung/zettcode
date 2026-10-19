<script setup lang="ts">
import type { DonutResult } from "../../core/chart.js";

withDefaults(
  defineProps<{
    result: DonutResult;
    size?: number;
    radius?: number;
    stroke?: number;
    active?: number | null;
    label?: string;
  }>(),
  { size: 128, radius: 52, stroke: 11, active: null, label: "Share of the total" },
);
</script>

<template>
  <svg
    class="donut"
    :class="{ hovering: active !== null }"
    :width="size"
    :height="size"
    :viewBox="`0 0 ${size} ${size}`"
    role="img"
    :aria-label="label"
  >
    <circle class="donut-track" :cx="size / 2" :cy="size / 2" :r="radius" :stroke-width="stroke" />
    <circle
      v-for="(slice, index) in result.slices"
      :key="index"
      class="donut-slice"
      :class="[`tone-${slice.tone}`, { active: active === index }]"
      :data-slice="index"
      :cx="size / 2"
      :cy="size / 2"
      :r="radius"
      :stroke-width="active === index ? stroke + 3 : stroke"
      :stroke-dasharray="slice.dasharray"
      :stroke-dashoffset="slice.dashoffset"
      :transform="`rotate(-90 ${size / 2} ${size / 2})`"
    >
      <title>{{ slice.name }}: {{ slice.percent }}%</title>
    </circle>
  </svg>
</template>

<style>
.donut {
  display: block;
  overflow: visible;
}

.donut-track {
  fill: none;
  stroke: var(--wash-2);
}

.donut-slice {
  fill: none;
  transition: opacity 0.15s, stroke-width 0.15s;
}

.donut.hovering .donut-slice:not(.active) {
  opacity: 0.25;
}

.donut-slice.tone-green {
  stroke: var(--green);
}

.donut-slice.tone-teal {
  stroke: var(--teal);
}

.donut-slice.tone-amber {
  stroke: var(--amber);
}

.donut-slice.tone-blue {
  stroke: var(--blue);
}

.donut-slice.tone-violet {
  stroke: var(--violet);
}

.donut-slice.tone-red {
  stroke: var(--red);
}

.donut-slice.tone-muted {
  stroke: var(--faint);
}

.swatch {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
  background: var(--faint);
}

.swatch.green {
  background: var(--green);
}

.swatch.teal {
  background: var(--teal);
}

.swatch.amber {
  background: var(--amber);
}

.swatch.blue {
  background: var(--blue);
}

.swatch.violet {
  background: var(--violet);
}

.swatch.red {
  background: var(--red);
}
</style>
