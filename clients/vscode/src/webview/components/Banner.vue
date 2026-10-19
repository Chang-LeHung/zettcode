<script setup lang="ts">
import { computed } from "vue";

import { post, state } from "../store.js";

type Level = "info" | "warn" | "error";

const banner = computed<{ level: Level; title: string; text: string; action?: string; run?: () => void } | null>(() => {
  const ui = state.ui;
  if (ui === null) {
    return null;
  }
  if (ui.server.status === "error") {
    return {
      level: "error",
      title: "The server is not running",
      text: ui.server.message,
      action: "Restart",
      run: () => post({ type: "restart-server" }),
    };
  }
  if (ui.server.status === "starting") {
    return { level: "info", title: "Starting the server", text: ui.server.message };
  }
  if (ui.session?.locked === true) {
    return {
      level: "warn",
      title: "This session is open elsewhere",
      text: "Another process has it. Close it there or start a new session.",
      action: "New session",
      run: () => post({ type: "new-session" }),
    };
  }
  return null;
});
</script>

<template>
  <div v-if="banner" id="banner" class="banner" :class="banner.level" role="status">
    <span v-if="banner.level === 'info'" class="spinner" />
    <span v-else class="dot" />
    <div class="banner-copy">
      <strong>{{ banner.title }}</strong>
      <span>{{ banner.text }}</span>
    </div>
    <button v-if="banner.action" class="btn small" type="button" @click="banner.run?.()">{{ banner.action }}</button>
  </div>
</template>

<style>
.banner {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 10px 12px 0;
  padding: 9px 12px;
  border-radius: var(--r-m);
  border: 1px solid var(--line);
  background: var(--wash);
  font-size: var(--small);
}

.banner-copy {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  line-height: 1.4;
}

.banner-copy span {
  color: var(--muted);
  overflow-wrap: anywhere;
}

.banner.error {
  border-color: color-mix(in srgb, var(--red) 40%, transparent);
  background: color-mix(in srgb, var(--red) 8%, transparent);
}

.banner.error .dot {
  background: var(--red);
}

.banner.warn {
  border-color: color-mix(in srgb, var(--amber) 40%, transparent);
  background: color-mix(in srgb, var(--amber) 8%, transparent);
}

.banner.warn .dot {
  background: var(--amber);
}
</style>
