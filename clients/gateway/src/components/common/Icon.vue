<script setup lang="ts">
import { computed } from "vue";
import { FILLED, ICONS, type IconName } from "./icons";

const props = defineProps<{ name: IconName; size?: "sm" | "xs" }>();
const markup = computed(() => ICONS[props.name]);
</script>

<template>
  <svg
    class="i"
    :class="[size, { fill: FILLED.has(name) }]"
    viewBox="0 0 24 24"
    aria-hidden="true"
    v-html="markup"
  />
</template>
