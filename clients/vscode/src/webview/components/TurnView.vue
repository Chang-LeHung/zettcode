<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from "vue";

import { formatDuration, formatTokens } from "../../core/format.js";
import { isAnnouncement, type AnnouncementBlock, type Turn } from "../../core/state.js";
import { COMPACT_TURN, openLightbox, post, state, toggleTurn } from "../store.js";
import BlockView from "./BlockView.vue";
import ChangesCard from "./ChangesCard.vue";
import Icon from "./Icon.vue";
import Receipt from "./Receipt.vue";

const props = defineProps<{ turn: Turn }>();

const folded = computed(() => state.collapsed.has(props.turn.id));
/** What a line across the view says, when this turn is only that: a change of model, effort or permission. */
const rule = computed(() => {
  const block = props.turn.blocks[0];
  return isAnnouncement(props.turn) && block?.kind === "announcement" ? (block as AnnouncementBlock).text : null;
});
const hasUser = computed(() => Boolean(props.turn.prompt || props.turn.images.length || props.turn.imageCount));
/** A row a command made, such as a compaction, is not something the reader said to the model. */
const isCommand = computed(() => props.turn.id.startsWith(COMPACT_TURN));

/**
 * When the message was sent. A conversation read back from the store has no send times (its turns carry the moment it
 * was opened), so those show none rather than a wrong one.
 */
const sentAt = computed(() => (props.turn.id.startsWith("history-") ? null : new Date(props.turn.startedAt)));
const clock = computed(() =>
  sentAt.value === null ? "" : sentAt.value.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }),
);
const fullTime = computed(() => (sentAt.value === null ? "" : sentAt.value.toLocaleString()));

const copied = ref(false);
let copiedTimer: number | undefined;

function copyPrompt(): void {
  post({ type: "copy", text: props.turn.prompt });
  copied.value = true;
  window.clearTimeout(copiedTimer);
  copiedTimer = window.setTimeout(() => {
    copied.value = false;
  }, 1600);
}

/** Put the message back in the box to change it and send it again. */
function editPrompt(): void {
  state.draft = props.turn.prompt;
  state.focus += 1;
}

onBeforeUnmount(() => window.clearTimeout(copiedTimer));

function isStep(kind: string): boolean {
  return kind === "tool" || kind === "approval" || kind === "question" || kind === "reasoning";
}

/** Everything from the first step to the last sits on one rail, narration between steps included. */
const layout = computed(() => {
  const blocks = props.turn.blocks;
  let first = -1;
  let last = -1;
  blocks.forEach((block, index) => {
    if (isStep(block.kind)) {
      first = first < 0 ? index : first;
      last = index;
    }
  });
  const entry = (index: number) => ({ block: blocks[index]!, index, key: blockKey(index) });
  const range = (from: number, to: number) => Array.from({ length: Math.max(0, to - from) }, (_, offset) => entry(from + offset));
  if (first < 0) {
    return { before: range(0, blocks.length), rail: [], after: [] };
  }
  return { before: range(0, first), rail: range(first, last + 1), after: range(last + 1, blocks.length) };
});

function blockKey(index: number): string {
  const block = props.turn.blocks[index];
  if (block?.kind === "tool") {
    return `tool:${block.tool.callId}`;
  }
  if (block?.kind === "approval" || block?.kind === "question") {
    return `${block.kind}:${block.callId}`;
  }
  return `${block?.kind}:${index}`;
}

const summary = computed(() => {
  const turn = props.turn;
  const bits: string[] = [];
  const steps = turn.blocks.filter((block) => block.kind === "tool").length;
  if (steps) {
    bits.push(`${steps} tool${steps === 1 ? "" : "s"}`);
  }
  if (turn.finishedAt !== undefined) {
    bits.push(formatDuration(Math.max(0, turn.finishedAt - turn.startedAt)));
  }
  if (turn.usage) {
    bits.push(`${formatTokens(turn.usage.input_tokens + turn.usage.output_tokens)} tokens`);
  }
  const files = state.changes[turn.id]?.length;
  if (files) {
    bits.push(`${files} file${files === 1 ? "" : "s"} changed`);
  }
  return bits.filter(Boolean).join(" · ");
});
</script>

<template>
  <section v-if="rule !== null" class="turn announce" :data-id="turn.id">
    <div class="rule" role="separator" :aria-label="rule"><span>{{ rule }}</span></div>
  </section>

  <section v-else class="turn" :class="{ aside: turn.aside, command: isCommand, folded }" :data-id="turn.id">
    <div v-if="hasUser && !isCommand" class="user">
      <div class="user-bubble" :class="{ flash: state.flashed === turn.id }">
        <div v-if="turn.prompt" class="user-text">{{ turn.prompt }}</div>
        <div v-if="turn.images.length" class="thumbs">
          <img
            v-for="(image, index) in turn.images"
            :key="index"
            class="thumb zoomable"
            :src="`data:${image.mediaType};base64,${image.data}`"
            alt="attached image"
            title="Open the picture"
            @click="openLightbox({ kind: 'image', src: `data:${image.mediaType};base64,${image.data}`, title: `Picture ${index + 1} of ${turn.images.length}` })"
          />
        </div>
        <div v-if="turn.imageCount" class="image-count">{{ turn.imageCount }} image(s)</div>
      </div>
      <div class="user-meta">
        <span v-if="clock" class="user-time" :title="fullTime">{{ clock }}</span>
        <button
          v-if="turn.prompt"
          class="icon-btn meta-btn"
          :class="{ done: copied }"
          type="button"
          :title="copied ? 'Copied' : 'Copy message'"
          :aria-label="copied ? 'Copied' : 'Copy message'"
          @click="copyPrompt"
        >
          <Icon :name="copied ? 'check' : 'copy'" :size="13" />
        </button>
        <button
          v-if="turn.prompt && !turn.aside"
          class="icon-btn meta-btn"
          type="button"
          title="Edit and resend"
          aria-label="Edit and resend"
          @click="editPrompt"
        >
          <Icon name="pencil" :size="13" />
        </button>
        <button
          v-if="!turn.aside"
          class="icon-btn meta-btn fold"
          type="button"
          :title="folded ? 'Expand this request' : 'Collapse this request'"
          :aria-expanded="!folded"
          @click="toggleTurn(turn.id)"
        >
          <Icon :name="folded ? 'right' : 'down'" :size="13" />
        </button>
      </div>
    </div>

    <div v-if="folded" class="folded-line">{{ summary || "Collapsed" }}</div>

    <div v-else class="assistant" :class="{ bare: isCommand }">
      <div v-if="turn.aside && !isCommand" class="label">Aside · not added to the conversation</div>
      <div v-if="turn.resumed" class="label">Resumed the interrupted request</div>

      <BlockView v-for="item in layout.before" :key="item.key" :turn="turn" :block="item.block" :index="item.index" />
      <div v-if="layout.rail.length" class="rail">
        <BlockView v-for="item in layout.rail" :key="item.key" :turn="turn" :block="item.block" :index="item.index" />
      </div>
      <BlockView v-for="item in layout.after" :key="item.key" :turn="turn" :block="item.block" :index="item.index" />

      <div v-if="turn.status === 'failed' && turn.error" class="turn-error">{{ turn.error }}</div>
      <div v-else-if="turn.stop?.message" class="turn-note">{{ turn.stop.message }}</div>
      <ChangesCard :turn-id="turn.id" />
      <Receipt v-if="!isCommand" :turn="turn" />
    </div>
  </section>
</template>

<style>
.turn {
  min-width: 0;
  padding: 14px 0 6px;
  scroll-margin-top: 4px;
}

.turn + .turn {
  border-top: 1px solid var(--line);
}

.turn.command + .turn,
.turn + .turn.command,
.turn.announce,
.turn.announce + .turn {
  border-top: 0;
}

/* A change of model, effort or permission: one line across the view with its words in the middle, as the terminal does. */
.turn.announce {
  padding: 8px 0 4px;
}

.rule {
  display: flex;
  align-items: center;
  gap: 12px;
  color: var(--muted);
  font-size: var(--small);
}

.rule::before,
.rule::after {
  content: "";
  flex: 1 1 16px;
  height: 1px;
  background: var(--line-strong);
}

.rule span {
  flex: 0 1 auto;
  text-align: center;
  overflow-wrap: anywhere;
}

/* The reader's message sits on the right, the way a chat does, with its time and actions underneath on hover. */
.user {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 2px;
}

.user-bubble {
  max-width: 88%;
  min-width: 0;
  padding: 9px 14px;
  border-radius: var(--r-l);
  background: var(--wash-2);
  font-size: var(--text);
}

.turn.aside .user-bubble {
  background: transparent;
  border: 1px dashed var(--line-strong);
}

/* Where a jump from the rail landed: a ring that opens out and fades, once. */
.user-bubble.flash {
  animation: bubble-flash 1.2s ease-out;
}

@keyframes bubble-flash {
  from {
    box-shadow: 0 0 0 0 color-mix(in srgb, var(--accent) 65%, transparent);
    background: color-mix(in srgb, var(--accent) 18%, var(--wash-2));
  }
  to {
    box-shadow: 0 0 0 9px color-mix(in srgb, var(--accent) 0%, transparent);
    background: var(--wash-2);
  }
}

.user-text {
  max-height: 260px;
  overflow-y: auto;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.thumbs {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
  margin-top: 6px;
}

.thumb {
  max-width: 120px;
  max-height: 90px;
  border-radius: var(--r-s);
  border: 1px solid var(--line);
  object-fit: cover;
}

.image-count {
  margin-top: 4px;
  color: var(--muted);
  font-size: var(--tiny);
}

.user-meta {
  display: flex;
  align-items: center;
  gap: 2px;
  min-height: 26px;
  padding-right: 4px;
  opacity: 0;
  transition: opacity 0.12s;
}

.turn:hover .user-meta,
.turn.folded .user-meta,
.user-meta:focus-within {
  opacity: 1;
}

.user-time {
  margin-right: 6px;
  color: var(--faint);
  font-size: var(--small);
  font-variant-numeric: tabular-nums;
}

.meta-btn {
  width: 24px;
  height: 24px;
}

.meta-btn.done {
  color: var(--accent);
}

.folded-line {
  margin: 6px 0 2px;
  text-align: right;
  color: var(--faint);
  font-size: var(--small);
}

.assistant {
  margin-top: 8px;
  padding: 0 2px;
}

.assistant.bare {
  margin-top: 0;
}

.assistant > .md,
.rail > .md {
  margin: 4px 0;
  font-size: var(--text);
}

.label {
  margin-bottom: 8px;
  color: var(--faint);
  font-size: var(--tiny);
  letter-spacing: 0.02em;
}

/* The rail: one line from the first step to the last, whatever sits between. */
.rail {
  position: relative;
  margin: 6px 0 10px;
  padding-left: 20px;
}

.rail::before {
  content: "";
  position: absolute;
  left: 6px;
  top: 11px;
  bottom: 11px;
  width: 1px;
  background: var(--line-strong);
}

.step {
  position: relative;
}

.step-dot {
  position: absolute;
  left: -18px;
  top: 10px;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--faint);
  box-shadow: 0 0 0 3px var(--bg);
}

.step-dot.blue {
  background: var(--blue);
}

.step-dot.amber {
  background: var(--amber);
}

.step-dot.green {
  background: var(--green);
}

.step-dot.teal {
  background: var(--teal);
}

.step-dot.orange {
  background: var(--orange);
}

.step-dot.violet {
  background: var(--violet);
}

.step-dot.red {
  background: var(--red);
}

.step-dot.rose {
  background: var(--rose);
}

.step-dot.pulse {
  animation: pulse 1.3s ease-in-out infinite;
}

.reasoning .step-dot {
  top: 10px;
}

/* A card's dot lines up with its heading, not with the top of the card. */
.approval .step-dot,
.question .step-dot {
  top: 15px;
}

.turn-error {
  margin-top: 10px;
  padding: 9px 12px;
  border: 1px solid color-mix(in srgb, var(--red) 40%, transparent);
  border-radius: var(--r-m);
  background: color-mix(in srgb, var(--red) 8%, transparent);
  color: var(--red);
  font-size: var(--small);
  max-height: 220px;
  overflow-y: auto;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.turn-note {
  margin-top: 8px;
  max-height: 160px;
  overflow-y: auto;
  color: var(--muted);
  font-size: var(--small);
  white-space: pre-wrap;
}
</style>
