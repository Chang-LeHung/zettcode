<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from "vue";

import { cleanOutput } from "../../core/format.js";
import { post } from "../store.js";
import Icon from "./Icon.vue";

const props = withDefaults(
  defineProps<{
    /** `terminal` is a command and what it printed; `code` is a file or a search result. */
    variant?: "terminal" | "code";
    /** The command, or the file the text came from. */
    title?: string;
    text: string;
    running?: boolean;
    failed?: boolean;
    /** Lines shown before the rest folds behind a button. */
    limit?: number;
    emptyLabel?: string;
  }>(),
  { variant: "code", title: "", running: false, failed: false, limit: 14, emptyLabel: "No output" },
);

const expanded = ref(false);
const lines = computed(() => {
  const clean = cleanOutput(props.text);
  return clean ? clean.split("\n") : [];
});
const shown = computed(() => (expanded.value ? lines.value : lines.value.slice(0, props.limit)).join("\n"));
const hidden = computed(() => Math.max(0, lines.value.length - props.limit));

const copied = ref(false);
let copiedTimer: number | undefined;

function copy(): void {
  post({ type: "copy", text: props.variant === "terminal" ? `${props.title}\n${lines.value.join("\n")}`.trim() : lines.value.join("\n") });
  // Confirmed on the button itself, which then turns back.
  copied.value = true;
  window.clearTimeout(copiedTimer);
  copiedTimer = window.setTimeout(() => {
    copied.value = false;
  }, 1500);
}

onBeforeUnmount(() => window.clearTimeout(copiedTimer));
</script>

<template>
  <div class="out" :class="[variant, { failed }]">
    <div v-if="title || variant === 'terminal'" class="out-head">
      <span v-if="variant === 'terminal'" class="out-prompt">$</span>
      <span class="out-title" :title="title">{{ title }}</span>
      <button
        class="out-copy icon-btn"
        :class="{ done: copied }"
        type="button"
        :title="copied ? 'Copied' : 'Copy'"
        :aria-label="copied ? 'Copied' : 'Copy'"
        @click="copy"
      >
        <Icon :name="copied ? 'check' : 'copy'" :size="12" />
      </button>
    </div>
    <div v-if="running && !lines.length" class="out-state"><span class="spinner" />Running…</div>
    <pre v-else-if="lines.length" class="out-body"><code>{{ shown }}</code></pre>
    <div v-else class="out-state quiet">{{ emptyLabel }}</div>
    <button v-if="hidden > 0" class="out-more" type="button" @click="expanded = !expanded">
      <Icon :name="expanded ? 'fold' : 'unfold'" :size="12" />{{ expanded ? "Show less" : `Show ${hidden} more line${hidden === 1 ? "" : "s"}` }}
    </button>
  </div>
</template>

<style>
.out {
  margin: 4px 0;
  border: 1px solid var(--line);
  border-radius: var(--r-m);
  background: var(--wash);
  overflow: hidden;
}

.out.terminal {
  background: color-mix(in srgb, var(--bg) 55%, #000 8%);
  border-color: var(--line-strong);
}

.out.failed {
  border-color: color-mix(in srgb, var(--red) 45%, transparent);
}

.out-head {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 7px 6px 7px 12px;
  border-bottom: 1px solid var(--line);
  background: var(--wash);
  font-family: var(--mono);
  font-size: var(--code-size);
  line-height: 1.5;
}

.out-prompt {
  color: var(--teal);
  font-weight: 700;
  user-select: none;
}

.out-title {
  flex: 1;
  min-width: 0;
  /* A command can run to a screenful; the card shows the first few lines and scrolls the rest. */
  max-height: calc(var(--code-size) * 1.5 * 4);
  overflow-y: auto;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.out-copy {
  position: relative;
  width: 22px;
  height: 22px;
  margin-top: -1px;
  flex-shrink: 0;
  opacity: 0;
}

.out-copy.done::after {
  content: "Copied";
  position: absolute;
  top: -3px;
  right: calc(100% + 6px);
  padding: 4px 10px;
  border-radius: 8px;
  background: var(--raised);
  border: 1px solid var(--line-strong);
  box-shadow: var(--shadow);
  color: var(--fg);
  font-family: var(--font);
  font-size: var(--small);
  white-space: nowrap;
  pointer-events: none;
  animation: rise 0.12s ease-out;
  z-index: 5;
}

.out:hover .out-copy,
.out-copy:focus-visible,
.out-copy.done {
  opacity: 1;
}

.out-copy.done {
  color: var(--accent);
}

.out-body {
  margin: 0;
  padding: 9px 12px;
  max-height: 360px;
  overflow: auto;
  font-family: var(--mono);
  font-size: var(--code-size);
  line-height: 1.55;
  color: var(--muted);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.out.terminal .out-body {
  color: color-mix(in srgb, var(--fg) 82%, transparent);
}

.out.failed .out-body {
  color: color-mix(in srgb, var(--red) 80%, var(--fg));
}

.out-body code {
  font: inherit;
}

.out-state {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 12px;
  color: var(--muted);
  font-size: var(--small);
}

.out-state.quiet {
  color: var(--faint);
  font-style: italic;
}

.out-more {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 5px 12px;
  border: 0;
  border-top: 1px solid var(--line);
  background: none;
  color: var(--muted);
  font-size: var(--tiny);
  text-align: left;
}

.out-more:hover {
  background: var(--wash-2);
  color: var(--fg);
}
</style>
