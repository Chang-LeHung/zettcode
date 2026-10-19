<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";

import { describeTool, noticePlain, withoutEllipsis } from "../../core/format.js";
import { state } from "../store.js";
import Shimmer from "./Shimmer.vue";

const now = ref(Date.now());
let timer: number | undefined;

const ui = computed(() => state.ui);
const running = computed(() => {
  for (let index = state.turns.length - 1; index >= 0; index -= 1) {
    const turn = state.turns[index];
    if (turn !== undefined && turn.finishedAt === undefined) {
      return turn;
    }
  }
  return null;
});
const active = computed(() => {
  const turn = running.value;
  if (turn === null) {
    return null;
  }
  for (let index = turn.blocks.length - 1; index >= 0; index -= 1) {
    const block = turn.blocks[index];
    if (block?.kind === "tool" && block.tool.status === "running") {
      return block.tool;
    }
  }
  return null;
});

const waiting = computed(() => ui.value?.pending?.kind ?? null);
const visible = computed(() => ui.value?.busy === true || waiting.value !== null);
/** The whole request's state, as the terminal words it: Processing, or what it is waiting for. */
const label = computed(() => {
  if (waiting.value === "approval") {
    return "Waiting for your approval";
  }
  if (waiting.value === "question") {
    return "Waiting for your answer";
  }
  return "Processing";
});
/** The step it is on, when it is on one the reader can name; before the first step, the latest word on a start. */
const detail = computed(() => {
  if (waiting.value !== null) {
    return "";
  }
  const tool = active.value;
  if (tool) {
    return describeTool(tool.name, tool.arguments).verb;
  }
  // An MCP server starting can take long enough to need explaining: its progress line is what is happening now.
  const last = running.value?.blocks[running.value.blocks.length - 1];
  return last?.kind === "notice" && last.level !== "warn" ? withoutEllipsis(noticePlain(last.text)) : "";
});
const elapsed = computed(() => {
  const turn = running.value;
  if (turn === null) {
    return "";
  }
  const seconds = Math.max(0, Math.floor((now.value - turn.startedAt) / 1000));
  const minutes = Math.floor(seconds / 60);
  return minutes > 0 ? `${minutes}:${String(seconds % 60).padStart(2, "0")}` : `${seconds}s`;
});

/** The clock ticks only while a request does, so an idle view holds no timer. */
watch(
  visible,
  (on) => {
    window.clearInterval(timer);
    timer = undefined;
    if (on) {
      now.value = Date.now();
      timer = window.setInterval(() => {
        now.value = Date.now();
      }, 1000);
    }
  },
  { immediate: true },
);

onBeforeUnmount(() => window.clearInterval(timer));
</script>

<template>
  <div v-if="visible" id="live-status" class="live" aria-live="polite">
    <span v-if="waiting" class="dot pulse waiting" />
    <span class="live-label"><Shimmer v-if="!waiting" :text="label" /><template v-else>{{ label }}</template></span>
    <span v-if="detail" class="live-detail"><Shimmer :text="detail" /></span>
    <span v-if="elapsed" class="live-time" title="Time since the request started">{{ elapsed }}</span>
    <span class="live-hint">esc to stop</span>
  </div>
</template>

<style>
.live {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 10px 2px 4px;
  color: var(--muted);
  font-size: var(--small);
}

.live .dot.waiting {
  background: var(--amber);
}

.live-detail {
  min-width: 0;
  max-width: 60%;
  flex: 0 1 auto;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding: 0 7px;
  border: 1px solid var(--line);
  border-radius: 999px;
  color: var(--muted);
  font-size: var(--tiny);
  line-height: 18px;
}

.live-detail .shimmer {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: top;
}

.live-time {
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
}

.live-hint {
  margin-left: auto;
  flex-shrink: 0;
  white-space: nowrap;
  color: var(--faint);
  font-size: var(--tiny);
}
</style>
