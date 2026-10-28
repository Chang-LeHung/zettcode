<script setup lang="ts">
import { computed } from "vue";
import { t } from "../../i18n";
import { duration } from "../../lib/format";
import type { Thread } from "../../types";

const props = defineProps<{ thread: Thread }>();

const rows = computed(() => {
  const thread = props.thread;
  const found: [string, string][] = [
    [t("Session id"), thread.id],
    [t("Kind"), t(thread.kind === "daemon" ? "Daemon" : thread.kind === "external" ? "External program" : "Session")],
    [t("Status"), t(thread.status)],
  ];
  if (thread.handle) found.push([t("Handle"), `@${thread.handle}`]);
  if (thread.workspace) found.push([t("Workspace"), thread.workspace]);
  if (thread.model) found.push([t("Model"), thread.effort ? `${thread.model} · ${thread.effort}` : thread.model]);
  if (thread.permission) found.push([t("Shell level"), thread.permission]);
  if (thread.pid) found.push([t("Process"), String(thread.pid)]);
  if (thread.kind === "daemon" && thread.started_at) found.push([t("Running for"), duration(Date.now() / 1000 - thread.started_at)]);
  return found;
});
</script>

<template>
  <div class="card info-card">
    <div v-for="[label, value] in rows" :key="label" class="kv">
      <span>{{ label }}</span>
      <span class="mono">{{ value }}</span>
    </div>
  </div>
</template>

<style>
.info-card { margin: 0 12px 8px; background: var(--surface-2); }
</style>
