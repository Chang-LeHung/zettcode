<script setup lang="ts">
import { state } from "../store.js";
</script>

<template>
  <!-- Above the transcript rather than over the message box: a long failure (a URL that could not be opened) must not
       cover what the reader is typing. -->
  <div id="toasts" class="toasts" aria-live="polite">
    <div v-for="item in state.toasts" :key="item.id" class="toast" :class="item.level" :title="item.text">
      <span class="dot" />{{ item.text }}
    </div>
  </div>
</template>

<style>
.toasts {
  position: absolute;
  left: 12px;
  right: 12px;
  top: 8px;
  z-index: 90;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  pointer-events: none;
}

.toast {
  position: relative;
  max-width: min(680px, 100%);
  padding: 8px 14px 8px 28px;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-m);
  background: var(--raised);
  box-shadow: var(--shadow);
  font-size: var(--small);
  line-height: 1.45;
  /* A message that carries a URL wraps instead of running off the view; past three lines it ends in an ellipsis and
     the whole of it is the element's title. */
  overflow-wrap: anywhere;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
  overflow: hidden;
  animation: rise 0.18s ease-out;
}

.toast .dot {
  position: absolute;
  left: 12px;
  top: 13px;
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
