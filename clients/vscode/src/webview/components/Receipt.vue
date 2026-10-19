<script setup lang="ts">
import { computed } from "vue";

import { formatDuration, formatTokens, stopLabel } from "../../core/format.js";
import type { Turn } from "../../core/state.js";

const props = defineProps<{ turn: Turn }>();

/** How the request ended. Success is the neutral word; only a request that did not finish cleanly has a colour. */
const status = computed(() => {
  const turn = props.turn;
  if (turn.status === "failed") {
    return { tone: "red", text: "Failed" };
  }
  if (turn.status === "cancelled") {
    return { tone: "amber", text: "Stopped" };
  }
  if (turn.stop) {
    return { tone: "amber", text: stopLabel(turn.stop.reason) };
  }
  return { tone: "", text: "Processed" };
});

const facts = computed(() => {
  const turn = props.turn;
  const out: { text: string; title: string }[] = [];
  if (turn.finishedAt !== undefined) {
    const duration = formatDuration(Math.max(0, turn.finishedAt - turn.startedAt));
    if (duration) {
      out.push({ text: duration, title: "Wall-clock time of this request" });
    }
  }
  const usage = turn.usage;
  if (usage) {
    out.push({ text: `↑ ${formatTokens(usage.input_tokens)}`, title: "Input tokens" });
    out.push({ text: `↓ ${formatTokens(usage.output_tokens)}`, title: "Output tokens" });
    if (usage.cache_read_tokens > 0 && usage.input_tokens > 0) {
      const share = (usage.cache_read_tokens / usage.input_tokens) * 100;
      out.push({ text: `${share.toFixed(1)}% cached`, title: "Input served from the cache" });
    }
    if (usage.requests > 1) {
      out.push({
        text: `${usage.requests} model calls`,
        title: "How many times the model was asked in this request: each round of thinking, using tools, then reading their results is one call",
      });
    }
    if (usage.seconds > 0 && usage.output_tokens > 0) {
      const rate = usage.output_tokens / usage.seconds;
      if (Number.isFinite(rate) && rate >= 1) {
        out.push({ text: `${rate.toFixed(rate < 10 ? 1 : 0)} tok/s`, title: "Output speed" });
      }
    }
  }
  const tools = turn.blocks.filter((block) => block.kind === "tool");
  if (tools.length) {
    const failed = tools.filter((block) => block.kind === "tool" && block.tool.status === "failed").length;
    out.push({
      text: `${tools.length} tool call${tools.length === 1 ? "" : "s"}${failed ? ` · ${failed} failed` : ""}`,
      title: "Tools the model used in this request: reading and editing files, running commands",
    });
  }
  return out;
});
</script>

<template>
  <div v-if="turn.status !== 'running' && !turn.aside" class="receipt">
    <span class="receipt-state" :class="status.tone"><i />{{ status.text }}</span>
    <span v-if="facts.length" class="receipt-sep" aria-hidden="true">·</span>
    <span v-for="fact in facts" :key="fact.title" class="receipt-fact" :title="fact.title">{{ fact.text }}</span>
  </div>
</template>

<style>
/* The words are text, not a control: they cannot be selected or pressed. Only a request that did not end cleanly has a colour. */
.receipt {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 2px 0;
  margin-top: 10px;
  color: var(--faint);
  font-size: var(--tiny);
  font-variant-numeric: tabular-nums;
  user-select: none;
  -webkit-user-select: none;
}

.receipt-state {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--muted);
  font-weight: 600;
}

.receipt-state i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}

.receipt-state.amber {
  color: var(--amber);
}

.receipt-state.red {
  color: var(--red);
}

.receipt-sep {
  margin: 0 8px;
  color: var(--faint);
}

/* The dot follows each item rather than leads it, so a line that wraps ends with one and never begins with one. */
.receipt-fact {
  white-space: nowrap;
}

.receipt-fact:not(:last-child)::after {
  content: "·";
  margin: 0 8px;
  color: var(--faint);
}
</style>
