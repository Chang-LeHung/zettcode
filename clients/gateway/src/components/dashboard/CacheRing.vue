<script setup lang="ts">
import { computed } from "vue";
import { percent } from "../../lib/format";

const props = withDefaults(defineProps<{ share: number | null; size?: number }>(), { size: 56 });

/** Green when most of the input came from the cache, amber when about half, red when little did. */
const tone = computed(() => (props.share === null ? "none" : props.share >= 0.7 ? "ok" : props.share >= 0.4 ? "warn" : "bad"));
const style = computed(() => ({
  width: `${props.size}px`,
  height: `${props.size}px`,
  "--share": `${(props.share ?? 0) * 360}deg`,
  fontSize: `${Math.round(props.size * 0.17)}px`,
}));
</script>

<template>
  <span class="ring" :class="tone" :style="style" role="img" :aria-label="percent(share)">
    <b>{{ percent(share) }}</b>
  </span>
</template>

<style>
.ring { --c: var(--muted); position: relative; flex: none; display: grid; place-items: center; border-radius: 50%; background: conic-gradient(var(--c) var(--share), var(--divider) 0); }
.ring::before { content: ""; position: absolute; inset: 14%; border-radius: 50%; background: var(--surface); }
.ring b { position: relative; font-weight: 650; font-variant-numeric: tabular-nums; }
.ring.ok { --c: var(--ok); }
.ring.warn { --c: var(--warn); }
.ring.bad { --c: var(--bad); }
</style>
