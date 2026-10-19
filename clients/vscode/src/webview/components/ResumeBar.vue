<script setup lang="ts">
import { post, state } from "../store.js";
import Icon from "./Icon.vue";
</script>

<template>
  <div v-if="state.ui?.resumable?.resumable === true && state.ui?.busy !== true" id="resume-bar" class="resume">
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
