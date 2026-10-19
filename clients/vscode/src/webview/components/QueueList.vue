<script setup lang="ts">
import { removeQueued, sendQueued, state } from "../store.js";
import Icon from "./Icon.vue";
</script>

<template>
  <div v-if="state.queue.length" id="queue" class="queue">
    <div class="queue-head">
      {{ state.ui?.busy === true ? "Follow-ups · sent when this run finishes" : "Waiting to send" }}
    </div>
    <div v-for="item in state.queue" :key="item.id" class="queue-item" :data-queue="item.id">
      <Icon name="follow" :size="13" class="queue-arrow" />
      <span class="queue-text" :title="item.text">{{ item.text }}</span>
      <span v-if="item.images.length" class="badge">{{ item.images.length }} image{{ item.images.length === 1 ? "" : "s" }}</span>
      <button
        class="btn small queue-steer"
        type="button"
        :title="state.ui?.busy === true ? 'Inject it into the run that is going' : 'Send it now'"
        @click="sendQueued(item.id)"
      >
        <Icon name="bolt" :size="11" />{{ state.ui?.busy === true ? "Steer" : "Send" }}
      </button>
      <button class="icon-btn queue-remove" type="button" title="Remove" aria-label="Remove" @click="removeQueued(item.id)">
        <Icon name="x" :size="12" />
      </button>
    </div>
  </div>
</template>

<style>
.queue {
  margin-bottom: 6px;
  border: 1px solid var(--line);
  border-radius: var(--r-m);
  background: var(--wash);
  overflow: hidden;
  animation: rise 0.18s ease-out;
}

.queue-head {
  padding: 5px 11px 3px;
  color: var(--faint);
  font-size: 11px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.queue-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 3px 5px 3px 11px;
}

.queue-item + .queue-item {
  border-top: 1px solid var(--line);
}

.queue-arrow {
  color: var(--faint);
}

.queue-text {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
}

.queue-steer {
  border-color: transparent;
  color: var(--amber);
}

.queue-steer:hover:not(:disabled) {
  background: color-mix(in srgb, var(--amber) 14%, transparent);
}
</style>
