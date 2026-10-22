<script setup lang="ts">
import { computed } from "vue";

import { describeTool, formatDuration, lineStats, summariseOutput, toolDetail, toolLanguage } from "../../core/format.js";
import type { ToolNode } from "../../core/state.js";
import { post, state, toggleIn } from "../store.js";
import Icon from "./Icon.vue";
import OutputBlock from "./OutputBlock.vue";

const props = defineProps<{ tool: ToolNode; turnId: string }>();

function toneOf(name: string): string {
  const bare = name.replace(/^.*__/, "").toLowerCase();
  if (["read_file", "read", "glob", "grep", "read_skill", "web_search", "fetch"].includes(bare)) {
    return "green";
  }
  if (["edit", "replace_in_file", "write_file", "write"].includes(bare)) {
    return "amber";
  }
  if (bare === "bash" || bare === "shell") {
    return "orange";
  }
  if (["task", "spawn_agent", "agent", "send_message"].includes(bare)) {
    return "rose";
  }
  return "muted";
}

const display = computed(() => describeTool(props.tool.name, props.tool.arguments));
const detail = computed(() => toolDetail(props.tool.name, props.tool.arguments));
const language = computed(() => toolLanguage(props.tool.name, props.tool.arguments));
const isBash = computed(() => /(^|__)(bash|shell)$/i.test(props.tool.name));
/** A command's card, and a failed call's, is open until you fold it; every other tool's body opens when you ask. */
const opensByDefault = computed(() => isBash.value || props.tool.status === "failed");
const open = computed(() =>
  opensByDefault.value ? !state.closedTools.has(props.tool.callId) : state.openTools.has(props.tool.callId),
);
const hasBody = computed(
  () => Boolean(detail.value || props.tool.output) || props.tool.status === "failed" || (isBash.value && props.tool.status === "running"),
);

function toggle(): void {
  toggleIn(opensByDefault.value ? state.closedTools : state.openTools, props.tool.callId);
}
const tone = computed(() => (props.tool.status === "failed" ? "red" : toneOf(props.tool.name)));
const target = computed(() => display.value.target || summariseOutput(props.tool.output, 90));
const status = computed(() => {
  const tool = props.tool;
  if (tool.status === "running") {
    return "running";
  }
  if (tool.status === "failed" || tool.status === "skipped") {
    return tool.status;
  }
  return tool.finishedAt !== undefined && tool.finishedAt - tool.startedAt > 400
    ? formatDuration(tool.finishedAt - tool.startedAt)
    : "";
});

const diffRows = computed(() =>
  language.value === "diff"
    ? detail.value.split("\n").map((line) => ({
        kind: line.startsWith("@@") ? "hunk" : line.startsWith("+") ? "add" : line.startsWith("-") ? "del" : "ctx",
        text: line,
      }))
    : [],
);

const adds = computed(() => diffRows.value.filter((row) => row.kind === "add").length);
const dels = computed(() => diffRows.value.filter((row) => row.kind === "del").length);
/** Lines an edit added and removed, shown on its row so the size of a change is known without opening it. */
const stats = computed(() =>
  props.tool.status === "failed" || props.tool.status === "skipped" ? null : lineStats(props.tool.name, props.tool.arguments),
);
const failed = computed(() => props.tool.status === "failed");
/** Why a call failed, in the tool's own words; a failure that said nothing still says that it failed. */
const reason = computed(() => props.tool.output.trim() || "The call failed without giving a reason.");

/** A file this request changed gets a link to its real diff. */
const changedPath = computed(() => {
  const path = display.value.path;
  if (!path) {
    return null;
  }
  const normal = path.replace(/\\/g, "/");
  const file = (state.changes[props.turnId] ?? []).find(
    (change) => normal === change.path || normal.endsWith(`/${change.path}`),
  );
  return file?.path ?? null;
});
</script>

<template>
  <div class="tool step" :class="[tool.status, { open }]">
    <span class="step-dot" :class="[tone, { pulse: tool.status === 'running' }]" />
    <button class="tool-head" type="button" :disabled="!hasBody" @click="toggle">
      <span class="tool-verb">{{ display.verb }}</span>
      <span
        v-if="display.path && display.target"
        class="tool-target link"
        role="link"
        :title="`Open ${display.path}`"
        @click.stop="post({ type: 'open', target: display.path })"
        >{{ display.target }}</span
      >
      <span v-else-if="target && !(isBash && open)" class="tool-target" :title="target">{{ target }}</span>
      <span v-else class="tool-target" />
      <span v-if="stats" class="tool-stats" title="Lines added and removed">
        <span class="plus">+{{ stats.added }}</span>
        <span v-if="stats.removed" class="minus">−{{ stats.removed }}</span>
      </span>
      <span v-if="status" class="tool-status" :class="tool.status">{{ status }}</span>
      <Icon v-if="hasBody" name="down" :size="12" class="tool-caret" />
    </button>
    <button
      v-if="changedPath"
      class="tool-diff"
      type="button"
      title="Open this file's diff"
      @click="post({ type: 'open-diff', turnId, path: changedPath })"
    >
      <Icon name="diff" :size="12" />Diff
    </button>
    <div v-if="open && hasBody" class="tool-body">
      <OutputBlock
        v-if="isBash"
        variant="terminal"
        :title="detail"
        :text="tool.output"
        :running="tool.status === 'running'"
        :failed="tool.status === 'failed'"
        empty-label="No output"
      />
      <template v-else-if="diffRows.length">
        <!-- A failed edit says why before it shows what it tried to change, and shows nothing as if it had landed. -->
        <OutputBlock v-if="failed" :text="reason" title="Why it failed" :failed="true" />
        <div class="out diffcard" :class="{ attempted: failed }">
          <div class="out-head">
            <span class="out-title">{{ failed ? "Not applied · " : "" }}{{ display.path || display.target }}</span>
            <template v-if="!failed">
              <span class="plus">+{{ adds }}</span>
              <span class="minus">−{{ dels }}</span>
            </template>
          </div>
          <pre class="diff-body"><span v-for="(row, index) in diffRows" :key="index" :class="row.kind">{{ row.text || " " }}</span></pre>
        </div>
      </template>
      <template v-else>
        <OutputBlock v-if="!tool.output && detail" :text="detail" title="Arguments" :limit="8" />
        <OutputBlock v-if="tool.output || failed" :text="failed ? reason : tool.output" :failed="failed" />
      </template>
    </div>
  </div>
</template>

<style>
.tool {
  position: relative;
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  margin-bottom: 4px;
}

.tool-head {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 5px 6px;
  border: 0;
  border-radius: 6px;
  background: none;
  font-size: 13px;
  line-height: 1.4;
  text-align: left;
}

.tool-head:not(:disabled):hover {
  background: var(--wash);
}

.tool-head:disabled {
  cursor: default;
}

.tool-verb {
  font-weight: 600;
  flex-shrink: 0;
}

.tool-target {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--muted);
  font-family: var(--mono);
  font-size: calc(var(--code-size) * 0.92);
}

.tool-target.link {
  cursor: pointer;
}

.tool-target.link:hover {
  color: var(--blue);
  text-decoration: underline;
}

.tool-stats {
  display: inline-flex;
  flex-shrink: 0;
  gap: 6px;
  font-family: var(--mono);
  font-size: var(--tiny);
  font-variant-numeric: tabular-nums;
}

.tool-stats .plus {
  color: var(--syn-add);
}

.tool-stats .minus {
  color: var(--syn-del);
}

.tool-status {
  flex-shrink: 0;
  color: var(--faint);
  font-size: var(--tiny);
  font-variant-numeric: tabular-nums;
}

.tool-status.failed {
  color: var(--red);
}

.tool-status.running {
  color: var(--muted);
}

.tool-caret {
  align-self: center;
  color: var(--faint);
  opacity: 0;
  transition: transform 0.12s, opacity 0.12s;
}

.tool-head:hover .tool-caret,
.tool.open .tool-caret {
  opacity: 1;
}

.tool.open .tool-caret {
  transform: rotate(180deg);
}

.tool-diff {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin: 1px 0 0 2px;
  padding: 0 8px 0 6px;
  height: 20px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: none;
  color: var(--muted);
  font-size: var(--tiny);
  flex-shrink: 0;
}

.tool-diff:hover {
  color: var(--fg);
  border-color: var(--line-strong);
  background: var(--wash);
}

.tool-body {
  flex-basis: 100%;
  margin: 2px 0 8px 6px;
}

.diff-body {
  margin: 0;
  padding: 6px 0;
  max-height: 340px;
  overflow: auto;
  font-family: var(--mono);
  font-size: var(--code-size);
  line-height: 1.55;
}

.diff-body span {
  display: block;
  padding: 0 12px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.diff-body .add {
  background: color-mix(in srgb, var(--green) 14%, transparent);
  color: var(--green);
}

.diff-body .del {
  background: color-mix(in srgb, var(--red) 13%, transparent);
  color: var(--red);
}

.diff-body .hunk {
  color: var(--faint);
  font-style: italic;
}

.diffcard .out-head {
  align-items: center;
}

/* What a failed edit tried to change: shown, but quieter than a change that happened. */
.diffcard.attempted {
  margin-top: 8px;
  opacity: 0.7;
}
</style>
