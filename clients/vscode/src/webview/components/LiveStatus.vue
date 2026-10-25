<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";

import { formatClock, noticePlain, withoutEllipsis } from "../../core/format.js";
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
/** The step it is on, when it is on one the reader cannot otherwise see; a tool's row already names it. */
const detail = computed(() => {
  if (waiting.value !== null) {
    return "";
  }
  // A tool's own row is the place its name belongs, and its time is on that row too: the live line says the one
  // thing that is true of the whole request — that it is still going — and how long it has been going.
  // An MCP server starting can take long enough to need explaining: its progress line is what is happening now.
  const last = running.value?.blocks[running.value.blocks.length - 1];
  return last?.kind === "notice" && last.level !== "warn" ? withoutEllipsis(noticePlain(last.text)) : "";
});
const elapsed = computed(() => {
  const turn = running.value;
  if (turn === null) {
    return "";
  }
  // `1m 19s`, not `1:19`: the words say what the number is, as the receipt's do.
  return formatClock(Math.max(0, now.value - turn.startedAt));
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
  <div v-if="visible" id="live-status" class="live-row" aria-live="polite">
    <span v-if="waiting" class="dot pulse waiting" />
    <span class="live-label"><Shimmer v-if="!waiting" :text="label" /><template v-else>{{ label }}</template></span>
    <span v-if="detail" class="live-detail"><Shimmer :text="detail" /></span>
    <span v-if="elapsed" class="live-time" title="Time since the request started">{{ elapsed }}</span>
    <span class="live-hint">esc to stop</span>
  </div>
</template>

<style>
/* A class of its own rather than `.live`: a block elsewhere in the transcript may well mark itself live too. */
.live-row {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 10px 2px 4px;
  color: var(--muted);
  font-size: var(--small);
}

.live-row .dot.waiting {
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
