<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from "vue";

import { post, state } from "../store.js";
import Icon from "./Icon.vue";

/** How long the bar stays: long enough to read once, short enough not to sit over the conversation. */
const VISIBLE_MS = 2000;

/**
 * The bar announces one interruption and then gets out of the way.
 *
 * It used to stay for as long as the request could be resumed, which is until the next prompt — permanently, from the
 * reader's side. `/continue` still works after it has gone; what is temporary is the announcement, not the ability.
 */
const visible = ref(false);
let timer: number | undefined;

watch(
  () => [state.ui?.resumable?.resumable === true && state.ui?.busy !== true, state.ui?.resumable?.description] as const,
  ([resumable]) => {
    window.clearTimeout(timer);
    visible.value = resumable;
    if (resumable) {
      timer = window.setTimeout(() => {
        visible.value = false;
      }, VISIBLE_MS);
    }
  },
  { immediate: true },
);

onBeforeUnmount(() => window.clearTimeout(timer));
</script>

<template>
  <div v-if="visible" id="resume-bar" class="resume">
    <span class="resume-icon"><Icon name="refresh" :size="13" /></span>
    <span class="resume-copy">
      <strong>Request interrupted</strong>
      <span>{{ state.ui?.resumable?.description ?? "It can pick up where it stopped." }}</span>
    </span>
    <button class="btn solid small" type="button" @click="post({ type: 'resume' })">
      Continue <span class="kbd">/continue</span>
    </button>
  </div>
</template>

<style>
.resume {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
  padding: 7px 8px 7px 11px;
  border: 1px solid color-mix(in srgb, var(--amber) 40%, transparent);
  border-radius: var(--r-m);
  background: color-mix(in srgb, var(--amber) 8%, transparent);
  animation: rise 0.18s ease-out;
}

.resume-icon {
  color: var(--amber);
  display: grid;
}

.resume-copy {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  line-height: 1.35;
  font-size: var(--small);
}

.resume-copy span {
  color: var(--muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.resume .btn .kbd {
  margin-left: 2px;
  border-color: color-mix(in srgb, var(--bg) 35%, transparent);
  color: color-mix(in srgb, var(--bg) 70%, transparent);
}
</style>
