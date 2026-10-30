<script setup lang="ts">
import { toasts } from "../../stores/ui";
</script>

<template>
  <div class="toasts" role="status" aria-live="polite">
    <div v-for="item in toasts" :key="item.id" class="toast" :class="item.kind">{{ item.text }}</div>
  </div>
</template>

<style>
.toasts {
  position: fixed; z-index: 40; left: 0; right: 0; top: calc(var(--safe-top) + 10px);
  display: flex; flex-direction: column; align-items: center; gap: 8px; pointer-events: none; padding: 0 14px;
}
.toast {
  max-width: 28rem; padding: 10px 16px; border-radius: 14px; background: rgba(28, 33, 38, 0.88); backdrop-filter: blur(14px) saturate(1.4); -webkit-backdrop-filter: blur(14px) saturate(1.4); color: #fff;
  font-size: 0.92rem; box-shadow: 0 4px 16px rgba(0, 0, 0, 0.35); animation: drop 0.32s cubic-bezier(0.22, 1, 0.36, 1); pointer-events: auto;
}
.toast.bad { background: rgba(190, 40, 36, 0.96); }
</style>
