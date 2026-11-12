<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from "vue";
import { net } from "../../api/http";

// A request that answers at once shows nothing; one that takes longer than a blink gets a bar, and the bar stays long enough to be seen.
const SHOW_AFTER = 180;
const SHOW_AT_LEAST = 420;

const visible = ref(false);
let showTimer: number | undefined;
let hideTimer: number | undefined;
let shownAt = 0;

watch(
  () => net.active > 0,
  (busy) => {
    if (busy) {
      window.clearTimeout(hideTimer);
      if (visible.value || showTimer !== undefined) return;
      showTimer = window.setTimeout(() => {
        showTimer = undefined;
        visible.value = true;
        shownAt = Date.now();
      }, SHOW_AFTER);
      return;
    }
    window.clearTimeout(showTimer);
    showTimer = undefined;
    if (!visible.value) return;
    hideTimer = window.setTimeout(() => (visible.value = false), Math.max(0, SHOW_AT_LEAST - (Date.now() - shownAt)));
  },
);

onBeforeUnmount(() => {
  window.clearTimeout(showTimer);
  window.clearTimeout(hideTimer);
});
</script>

<template>
  <div class="topbar" :class="{ on: visible }" role="progressbar" :aria-hidden="!visible" aria-busy="true"><i /></div>
</template>

<style>
.topbar {
  position: fixed; top: 0; left: 0; right: 0; height: 3px; z-index: 90; overflow: hidden; pointer-events: none;
  opacity: 0; transition: opacity 0.25s ease;
}
.topbar.on { opacity: 1; }
.topbar i {
  position: absolute; top: 0; bottom: 0; left: 0; width: 40%; border-radius: 3px;
  background: linear-gradient(90deg, transparent, var(--accent), transparent);
  animation: sweep 1.1s ease-in-out infinite;
}
@keyframes sweep { from { transform: translateX(-100%); } to { transform: translateX(250%); } }
</style>
