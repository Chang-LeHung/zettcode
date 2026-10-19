<script setup lang="ts">
import { state } from "../store.js";
</script>

<template>
  <div id="toasts" class="toasts" aria-live="polite">
    <div v-for="item in state.toasts" :key="item.id" class="toast" :class="item.level">
      <span class="dot" />{{ item.text }}
    </div>
  </div>
</template>

<style>
.toasts {
  position: absolute;
  left: 12px;
  right: 12px;
  bottom: 110px;
  z-index: 90;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  pointer-events: none;
}

.toast {
  display: flex;
  align-items: center;
  gap: 9px;
  max-width: 100%;
  padding: 8px 14px;
  border: 1px solid var(--line-strong);
  border-radius: 999px;
  background: var(--raised);
  box-shadow: var(--shadow);
  font-size: var(--small);
  animation: rise 0.18s ease-out;
}

.toast.warn .dot {
  background: var(--amber);
}

.toast.error .dot {
  background: var(--red);
}

.toast.info .dot {
  background: var(--blue);
}
</style>
