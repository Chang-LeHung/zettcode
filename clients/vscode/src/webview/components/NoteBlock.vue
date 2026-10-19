<script setup lang="ts">
import { computed } from "vue";

import { noticeMarkdown, noticePlain, withoutEllipsis } from "../../core/format.js";
import type { AnnouncementBlock, CompactionBlock, NoticeBlock, SteerBlock, Turn } from "../../core/state.js";
import { state, toggleIn } from "../store.js";
import Icon from "./Icon.vue";
import Markdown from "./Markdown.vue";
import Shimmer from "./Shimmer.vue";

const props = defineProps<{
  block: NoticeBlock | SteerBlock | CompactionBlock | AnnouncementBlock;
  turn: Turn;
  index: number;
}>();

const id = computed(() => `note:${props.turn.id}:${props.index}`);
const open = computed(() => state.openNotes.has(id.value));
/** A progress line that is the newest thing in a request still running is something happening now, so its words shimmer. */
const working = computed(
  () =>
    props.block.kind === "notice" &&
    props.block.level !== "warn" &&
    props.turn.status === "running" &&
    props.index === props.turn.blocks.length - 1,
);
/** A compaction can be opened to read the summary that stands in for the older messages. */
const readable = computed(() => props.block.kind === "compaction" && props.block.applied && Boolean(props.block.summary));
</script>

<template>
  <!-- News from the agent, such as an MCP server starting or failing: drawn through the same Markdown as an answer. -->
  <div
    v-if="block.kind === 'notice'"
    class="note notice"
    :class="`level-${block.level ?? 'info'}`"
    :role="block.level === 'warn' ? 'alert' : 'status'"
  >
    <Icon :name="block.level === 'warn' ? 'warn' : 'plug'" :size="13" />
    <Shimmer v-if="working" class="notice-text" :text="withoutEllipsis(noticePlain(block.text))" />
    <Markdown v-else class="notice-text" :text="noticeMarkdown(block.text)" />
  </div>

  <div v-else-if="block.kind === 'announcement'" class="note">{{ block.text }}</div>

  <div v-else-if="block.kind === 'steered'" class="note steered" :class="{ pending: block.pending }">
    <Icon name="bolt" :size="12" />
    <span>
      <strong>Steered</strong> {{ block.text }}
      <em v-if="block.pending" class="steer-hint">read at the model's next step</em>
    </span>
  </div>

  <!-- A running compaction shimmers; a finished one says so, and can be opened to read the summary it made. -->
  <div v-else-if="block.kind === 'compaction'" class="note-compaction" :class="{ open }">
    <div class="note compaction" :class="{ done: !block.running && block.applied }">
      <Shimmer v-if="block.running" text="Compacting the conversation" />
      <button
        v-else-if="readable"
        type="button"
        class="compaction-head"
        :aria-expanded="open"
        title="Show the summary the model now works from"
        @click="toggleIn(state.openNotes, id)"
      >
        <Icon name="check" :size="13" /><span>Conversation compacted</span>
        <Icon name="down" :size="12" class="compaction-caret" />
      </button>
      <template v-else-if="block.applied">
        <Icon name="check" :size="13" /><span>Conversation compacted</span>
      </template>
      <span v-else>Nothing to compact.</span>
    </div>
    <Markdown v-if="open && readable" class="compaction-summary" :text="block.summary ?? ''" />
  </div>
</template>

<style>
.note {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  margin: 8px 0;
  color: var(--muted);
  font-size: var(--small);
  white-space: pre-wrap;
}

.note.steered .icon {
  margin-top: 3px;
  color: var(--amber);
}

/* News from the agent: progress stays quiet, a warning has a colour and a bar, and a run of them reads as one list. */
.note.notice {
  align-items: flex-start;
  margin: 6px 0;
  white-space: normal;
}

.note.notice + .note.notice {
  margin-top: -2px;
}

.note.notice > .icon {
  margin-top: 4px;
  flex-shrink: 0;
}

.note.notice .notice-text {
  min-width: 0;
  font-size: var(--small);
  line-height: 1.5;
}

.note.notice .notice-text code {
  font-size: 0.95em;
}

.note.notice.level-warn {
  padding: 6px 10px;
  border-left: 2px solid var(--amber);
  border-radius: 0 var(--r-s) var(--r-s) 0;
  background: color-mix(in srgb, var(--amber) 8%, transparent);
  color: var(--fg);
}

.note.notice.level-warn > .icon {
  color: var(--amber);
}

.note.steered strong {
  margin-right: 4px;
  color: var(--fg);
  font-weight: 600;
}

.note.compaction {
  align-items: center;
}

.note.compaction.done {
  color: var(--accent);
}

.note.steered .steer-hint {
  margin-left: 6px;
  color: var(--faint);
  font-size: var(--tiny);
  font-style: normal;
}

.compaction-head {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 2px 6px 2px 0;
  border: 0;
  border-radius: var(--r-s);
  background: none;
  color: inherit;
  font: inherit;
}

.compaction-head:hover {
  color: var(--fg);
}

.compaction-caret {
  opacity: 0.6;
  transition: transform 0.12s;
}

.note-compaction.open .compaction-caret {
  transform: rotate(180deg);
}

/* The summary is the model's own text, kept to a scrolling panel so a long one does not push the conversation away. */
.compaction-summary {
  max-height: 320px;
  margin: 2px 0 8px 20px;
  padding-left: 12px;
  overflow-y: auto;
  border-left: 2px solid color-mix(in srgb, var(--accent) 40%, transparent);
  color: var(--muted);
  font-size: 13px;
}
</style>
