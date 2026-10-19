<script setup lang="ts">
import { computed } from "vue";

import { ICONS } from "../icons.js";

const props = withDefaults(defineProps<{ name: string; size?: number; fill?: boolean }>(), { size: 14, fill: false });
const paths = computed(() => ICONS[props.name] ?? []);
</script>

<template>
  <svg
    class="icon"
    :width="size"
    :height="size"
    viewBox="0 0 16 16"
    :fill="fill ? 'currentColor' : 'none'"
    stroke="currentColor"
    stroke-width="1.4"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path v-for="(d, index) in paths" :key="index" :d="d" />
  </svg>
</template>

<style>
.icon {
  flex-shrink: 0;
  display: block;
}
</style>
