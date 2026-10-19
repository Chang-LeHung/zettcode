<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";

import { formatTokens, permissionDescription, permissionLabel } from "../../core/format.js";
import { effortMeta, permissionMeta } from "../../core/levels.js";
import { contextPercent, contextRows, formatPercent } from "../context.js";
import { commandOf, parseSlash, runSlash, SLASH_COMMANDS } from "../commands.js";
import { closeOverlay, enqueue, openOverlay, post, state, toast } from "../store.js";
import AttachmentStrip from "./AttachmentStrip.vue";
import ChoiceMenu from "./ChoiceMenu.vue";
import ContextPopover from "./ContextPopover.vue";
import Donut from "./Donut.vue";
import EffortPips from "./EffortPips.vue";
import Icon from "./Icon.vue";
import ModelMenu from "./ModelMenu.vue";
import AddModelPanel from "./AddModelPanel.vue";
import QueueList from "./QueueList.vue";
import ResumeBar from "./ResumeBar.vue";

interface MenuItem {
  id: string;
  label: string;
  description: string;
  badge: string;
}

const field = ref<HTMLTextAreaElement | null>(null);
const mirror = ref<HTMLElement | null>(null);
const box = ref<HTMLElement | null>(null);
const offset = ref(0);
const caret = ref(0);
const active = ref(0);
const dismissed = ref(false);
/** The text in the box this instant, composing included; the draft only has what was committed. */
const live = ref(state.draft);
let mentionTimer: number | undefined;

const ui = computed(() => state.ui);
const busy = computed(() => ui.value?.busy === true);
const settings = computed(() => ui.value?.settings ?? null);
const permission = computed(() => settings.value?.permission ?? "ask");
const perm = computed(() => permissionMeta(permission.value));
const effortIndex = computed(() => settings.value?.efforts.indexOf(settings.value.effort ?? "") ?? 0);
const effort = computed(() =>
  effortMeta(settings.value?.effort ?? "", Math.max(0, effortIndex.value), settings.value?.efforts.length ?? 1),
);
const text = computed(() => state.draft.trim());

// -- the menu: slash commands and @ mentions ------------------------------

const before = computed(() => state.draft.slice(0, caret.value));
const slash = computed(() => /^\/([\w-]*)$/.exec(before.value));
const mention = computed(() => /(?:^|\s)@([\w./-]*)$/.exec(before.value));

const items = computed<MenuItem[]>(() => {
  if (dismissed.value) {
    return [];
  }
  if (slash.value !== null) {
    const query = slash.value[1] ?? "";
    return SLASH_COMMANDS.filter((command) => command.name.startsWith(query)).map((command) => ({
      id: command.name,
      label: `/${command.name}`,
      description: command.description,
      badge: "",
    }));
  }
  if (mention.value !== null && state.mentions?.query === (mention.value[1] ?? "")) {
    return state.mentions.items.map((item) => ({
      id: item.token,
      label: item.token,
      description: item.description,
      badge: item.kind,
    }));
  }
  return [];
});

watch(
  () => [slash.value?.[1], mention.value?.[1]],
  () => {
    active.value = 0;
    dismissed.value = false;
    window.clearTimeout(mentionTimer);
    if (mention.value !== null && slash.value === null) {
      const query = mention.value[1] ?? "";
      mentionTimer = window.setTimeout(() => post({ type: "mentions", query }), 120);
    }
  },
);

/** Put the caret at the end of the draft, once the box has the new text. */
function caretToEnd(): void {
  void nextTick(() => {
    const element = field.value;
    if (element === null) {
      return;
    }
    element.focus();
    element.setSelectionRange(element.value.length, element.value.length);
    caret.value = element.value.length;
  });
}

/**
 * Enter runs a command; Tab only completes it, so a command is never fired by reaching for the next word. A command
 * that takes something after its name (`/btw`, `/rename`) is completed either way, because running it bare would
 * only ask for what it is still waiting for.
 */
function choose(index: number, completeOnly = false): void {
  const item = items.value[index];
  if (item === undefined) {
    return;
  }
  if (slash.value !== null) {
    const command = commandOf(item.id);
    if (completeOnly || command?.args !== undefined) {
      state.draft = `/${item.id} `;
      caretToEnd();
      return;
    }
    state.draft = "";
    runSlash(item.id);
    return;
  }
  const at = before.value.lastIndexOf("@");
  const after = state.draft.slice(caret.value);
  state.draft = `${state.draft.slice(0, at)}${item.id} ${after}`;
  const position = at + item.id.length + 1;
  nextTick(() => {
    field.value?.focus();
    field.value?.setSelectionRange(position, position);
    caret.value = position;
  });
}

// -- the draft, coloured -------------------------------------------------------

interface Piece {
  text: string;
  kind: "plain" | "command" | "mention" | "ghost";
}

/**
 * The draft as pieces for the layer behind the box: a known `/command` and every `@mention` coloured, and, when a
 * command is typed and waiting for its argument, a faint hint of what goes there. The layer only colours; it never
 * changes the width of a character, so the caret in the box above it stays where the eye expects.
 */
const pieces = computed<Piece[]>(() => {
  const value = live.value;
  const out: Piece[] = [];
  let start = 0;
  const lead = /^\/([\w-]+)/.exec(value);
  const command = lead?.[1] === undefined ? undefined : commandOf(lead[1]);
  if (lead !== null && command !== undefined) {
    out.push({ text: lead[0], kind: "command" });
    start = lead[0].length;
  }
  const rest = value.slice(start);
  const mentions = /(^|\s)(@[\w./-]+)/g;
  let cursor = 0;
  for (let match = mentions.exec(rest); match !== null; match = mentions.exec(rest)) {
    const token = match[2] ?? "";
    const at = match.index + (match[1] ?? "").length;
    if (at > cursor) {
      out.push({ text: rest.slice(cursor, at), kind: "plain" });
    }
    out.push({ text: token, kind: "mention" });
    cursor = at + token.length;
  }
  if (cursor < rest.length) {
    out.push({ text: rest.slice(cursor), kind: "plain" });
  }
  if (command?.args !== undefined && /^\/[\w-]+ $/.test(value)) {
    out.push({ text: command.args, kind: "ghost" });
  }
  // A final line break would collapse in the layer and leave it a line short.
  out.push({ text: "\u200b", kind: "plain" });
  return out;
});

function syncScroll(): void {
  if (mirror.value !== null && field.value !== null) {
    mirror.value.scrollTop = field.value.scrollTop;
  }
}

// -- sending ----------------------------------------------------------------

/**
 * Enter sends. While a request runs it queues a follow-up; Ctrl/⌘+Enter, or the Steer button on a queued
 * message, injects it into the request that is going.
 */
function submit(steer = false): void {
  const message = state.draft.trim();
  if (!message) {
    if (state.attachments.length) {
      toast("Type a message to send with the image.", "info");
    }
    return;
  }
  if (ui.value === null || !ui.value.ready) {
    toast("Add a model first.", "warn");
    openOverlay("models");
    return;
  }
  const command = parseSlash(message);
  if (command !== null && state.attachments.length === 0) {
    state.draft = "";
    runSlash(command.name, command.rest);
    return;
  }
  if (busy.value) {
    if (steer) {
      post({ type: "steer", text: message });
    } else {
      enqueue(message, state.attachments);
      state.attachments = [];
    }
    state.draft = "";
    return;
  }
  post({
    type: "prompt",
    text: message,
    images: state.attachments.map((image) => ({ data: image.data, mediaType: image.mediaType })),
  });
  state.draft = "";
  state.attachments = [];
}

function onKeydown(event: KeyboardEvent): void {
  if (items.value.length > 0) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      active.value = (active.value + step + items.value.length) % items.value.length;
      // Only the keyboard scrolls to the row: a pointer moving over rows must not fight the wheel.
      void nextTick(() => document.querySelector("#menu .menu-item.active")?.scrollIntoView({ block: "nearest" }));
      return;
    }
    if (event.key === "Tab" || (event.key === "Enter" && !event.shiftKey)) {
      event.preventDefault();
      choose(active.value, event.key === "Tab");
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      dismissed.value = true;
      return;
    }
  }
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    submit(event.metaKey || event.ctrlKey);
    return;
  }
  if (event.key === "Escape" && busy.value && state.overlay === null) {
    post({ type: "cancel" });
  }
}

function track(): void {
  caret.value = field.value?.selectionStart ?? state.draft.length;
  follow();
}

/**
 * What the box holds right now. While an input method is composing (pinyin, kana), `v-model` leaves `state.draft` alone
 * until the word is chosen, but the box's own text is transparent and the layer behind it draws the letters, so that
 * layer must follow the box and not the draft, or the letters being typed would not be seen at all.
 */
function follow(): void {
  const element = field.value;
  if (element !== null && element.value !== live.value) {
    live.value = element.value;
    void nextTick(resize);
  }
}

watch(
  () => state.draft,
  (value) => {
    live.value = value;
  },
);

function resize(): void {
  const element = field.value;
  if (element !== null) {
    element.style.height = "auto";
    element.style.height = `${Math.min(element.scrollHeight, 220)}px`;
  }
}

watch(
  () => state.draft,
  async () => {
    await nextTick();
    resize();
    track();
    syncScroll();
  },
);

watch(
  () => state.focus,
  async () => {
    await nextTick();
    field.value?.focus();
    track();
  },
);

onBeforeUnmount(() => window.clearTimeout(mentionTimer));

// -- the menus that open over the box ----------------------------------------------

/** Each menu hangs over the control that opens it, kept inside the box. */
const ANCHORS: Record<string, { chip: string; width: number }> = {
  models: { chip: "model-chip", width: 340 },
  effort: { chip: "effort-chip", width: 220 },
  permission: { chip: "permission-chip", width: 340 },
};

watch(
  () => state.overlay,
  async (kind) => {
    const anchor = kind === null ? undefined : ANCHORS[kind];
    if (anchor === undefined) {
      offset.value = 0;
      return;
    }
    await nextTick();
    const chip = document.getElementById(anchor.chip);
    const frame = box.value;
    if (chip !== null && frame !== null) {
      const left = chip.getBoundingClientRect().left - frame.getBoundingClientRect().left;
      offset.value = Math.max(0, Math.min(left, frame.clientWidth - anchor.width));
    }
  },
);

function toggle(kind: "models" | "effort" | "permission"): void {
  if (state.overlay === kind) {
    closeOverlay();
  } else {
    openOverlay(kind);
  }
}

// -- the bar under the box ------------------------------------------------------

const report = computed(() => ui.value?.context ?? null);
const percent = computed(() => (report.value ? contextPercent(report.value) : 0));
const mini = computed(() => (report.value ? contextRows(report.value).ring : null));
const tight = computed(() => (percent.value >= 90 ? "full" : percent.value >= 70 ? "tight" : ""));
const contextOpen = computed(() => state.overlay === "context");

const placeholder = computed(() => (busy.value ? "Queue a follow-up…" : "Ask ZettCode…"));

/** What this whole conversation has spent: tokens in and out, how much came from the cache, and how fast it wrote. */
const stats = computed(() => {
  const usage = ui.value?.session?.usage;
  if (!usage || usage.requests <= 0) {
    return [];
  }
  const facts = [
    { text: `↑ ${formatTokens(usage.input_tokens)}`, title: "Input tokens, this session" },
    { text: `↓ ${formatTokens(usage.output_tokens)}`, title: "Output tokens, this session" },
  ];
  if (usage.cache_read_tokens > 0 && usage.input_tokens > 0) {
    const share = (usage.cache_read_tokens / usage.input_tokens) * 100;
    facts.push({ text: `${share.toFixed(1)}% cached`, title: "Input served from the provider's cache" });
  }
  if (usage.seconds > 0 && usage.output_tokens > 0) {
    const rate = usage.output_tokens / usage.seconds;
    if (Number.isFinite(rate)) {
      facts.push({ text: `${rate.toFixed(1)} tok/s`, title: "Output speed across the session's model calls" });
    }
  }
  facts.push({ text: `${usage.requests} call${usage.requests === 1 ? "" : "s"}`, title: "Model calls" });
  return facts;
});
const hint = computed(() =>
  busy.value
    ? "Enter queues a follow-up · ⌘/Ctrl+Enter steers · Esc stops"
    : "Enter send · Shift+Enter newline · / commands · @ files",
);
</script>

<template>
  <footer class="composer">
    <ResumeBar />
    <QueueList />
    <AttachmentStrip />

    <div ref="box" class="box" :class="{ busy }">
      <ContextPopover v-if="contextOpen" />
      <ModelMenu v-else-if="state.overlay === 'models'" :offset="offset" />
      <ChoiceMenu v-else-if="state.overlay === 'effort'" kind="effort" :offset="offset" />
      <ChoiceMenu v-else-if="state.overlay === 'permission'" kind="permission" :offset="offset" />
      <AddModelPanel v-else-if="state.overlay === 'add-model'" />

      <div v-if="items.length" id="menu" class="menu" role="listbox" @mousedown.prevent>
        <button
          v-for="(item, index) in items"
          :key="item.id"
          type="button"
          role="option"
          class="menu-item"
          :class="{ active: index === active }"
          :aria-selected="index === active"
          @mousedown.prevent
          @click="choose(index)"
          @pointerenter="active = index"
        >
          <span class="menu-label">{{ item.label }}</span>
          <span class="menu-desc">{{ item.description }}</span>
          <span v-if="item.badge" class="badge">{{ item.badge }}</span>
        </button>
      </div>

      <div class="field">
        <div ref="mirror" class="mirror" aria-hidden="true"><span
            v-for="(piece, index) in pieces"
            :key="index"
            :class="`piece-${piece.kind}`"
          >{{ piece.text }}</span></div>
        <textarea
          id="input"
          ref="field"
          v-model="state.draft"
          rows="1"
          :placeholder="placeholder"
          :aria-label="busy ? 'Queue a follow-up' : 'Message'"
          @keydown="onKeydown"
          @keyup="track"
          @click="track"
          @input="track"
          @compositionstart="follow"
          @compositionupdate="follow"
          @compositionend="follow"
          @scroll="syncScroll"
          @blur="dismissed = true"
          @focus="dismissed = false"
        />
      </div>

      <div class="bar">
        <button id="attach" class="icon-btn" type="button" title="Attach an image" aria-label="Attach an image" @click="post({ type: 'pick-images' })">
          <Icon name="clip" />
        </button>
        <button id="model-chip" class="chip strong" type="button" title="Model (/model)" :aria-expanded="state.overlay === 'models'" @click.stop="toggle('models')">
          {{ ui?.currentModel ?? (ui?.ready ? "Model" : "No model") }}<Icon name="down" :size="11" />
        </button>
        <button
          v-if="settings"
          id="effort-chip"
          :key="settings.effort ?? ''"
          class="chip effort"
          :class="[`tone-${effort.tone}`, `motion-${effort.motion}`]"
          type="button"
          title="Reasoning effort (/effort)"
          :aria-expanded="state.overlay === 'effort'"
          @click.stop="toggle('effort')"
        >
          <EffortPips v-if="settings.effort" :name="settings.effort" :index="effortIndex" :total="settings.efforts.length" />
          <span :class="{ 'fx-flow': effort.motion === 'flow', 'fx-aurora': effort.motion === 'aurora' }">{{ settings.effort ?? "Effort" }}</span>
        </button>
        <button
          v-if="settings"
          id="permission-chip"
          class="chip permission"
          :class="[`tone-${perm.tone}`, `risk-${perm.risk}`]"
          type="button"
          :title="`Shell permission: ${permissionDescription(permission)}`"
          :aria-expanded="state.overlay === 'permission'"
          @click.stop="toggle('permission')"
        >
          <Icon :name="perm.icon" :size="13" />{{ permissionLabel(permission) }}
        </button>

        <span class="spacer" />

        <button
          v-if="report && ui?.ready"
          id="context-chip"
          class="ctx"
          :class="[tight, { open: contextOpen }]"
          type="button"
          :title="`Context ${formatPercent(percent)}% used · ${formatTokens(report.used)} of ${formatTokens(report.window)} tokens`"
          aria-label="Context composition"
          :aria-expanded="contextOpen"
          @click.stop="contextOpen ? closeOverlay() : openOverlay('context')"
        >
          <Donut v-if="mini" :result="mini" :size="18" :radius="7" :stroke="3" label="Context composition" />
          <span>{{ formatPercent(percent) }}%</span>
        </button>

        <button v-if="busy" id="stop" class="stop" type="button" title="Stop the run (Esc)" aria-label="Stop" @click="post({ type: 'cancel' })">
          <Icon name="stop" :size="14" fill />
        </button>
        <button
          id="send"
          class="send"
          type="button"
          :disabled="!text"
          :title="!text ? 'Type a message' : busy ? 'Queue as a follow-up' : 'Send'"
          :aria-label="busy ? 'Queue a follow-up' : 'Send'"
          @click="submit(false)"
        >
          <Icon :name="busy ? 'follow' : 'up'" :size="15" />
        </button>
      </div>
    </div>
    <div class="foot">
      <div v-if="stats.length" id="session-stats" class="stats" aria-label="This session">
        <span v-for="fact in stats" :key="fact.title" class="stat" :title="fact.title">{{ fact.text }}</span>
      </div>
      <div id="input-hint" class="hint">{{ hint }}</div>
    </div>
  </footer>
</template>

<style>
.composer {
  position: relative;
  flex-shrink: 0;
  width: 100%;
  max-width: var(--column);
  margin: 0 auto;
  padding: 6px var(--gutter) 10px;
}

.box {
  position: relative;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-l);
  background: var(--input);
  transition: border-color 0.15s, box-shadow 0.15s;
}

.box:focus-within {
  border-color: color-mix(in srgb, var(--fg) 38%, transparent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--fg) 7%, transparent);
}

.box.busy {
  border-color: color-mix(in srgb, var(--accent) 45%, transparent);
}

.field {
  position: relative;
}

/* The layer behind the box colours the draft; the box above it keeps the caret and the selection. Both must set the
   same font, padding and wrapping, or the colours drift off the letters. */
.mirror,
#input {
  padding: 12px 14px 4px;
  font-family: var(--font);
  font-size: var(--text);
  font-weight: 400;
  line-height: 1.5;
  letter-spacing: normal;
  white-space: pre-wrap;
  overflow-wrap: break-word;
  word-break: normal;
}

.mirror {
  position: absolute;
  inset: 0;
  overflow: hidden;
  pointer-events: none;
  color: var(--fg);
}

.piece-command {
  color: var(--accent);
}

.piece-mention {
  color: var(--sky);
  background: color-mix(in srgb, var(--sky) 14%, transparent);
  border-radius: 3px;
}

.piece-ghost {
  color: var(--faint);
}

#input {
  position: relative;
  display: block;
  width: 100%;
  min-height: 46px;
  max-height: 220px;
  border: 0;
  outline: none;
  resize: none;
  background: transparent;
  /* The text is drawn by the layer behind; this box only carries the caret and the selection. */
  color: transparent;
  caret-color: var(--fg);
}

#input::placeholder {
  color: var(--faint);
}

.bar {
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 4px 6px 6px 6px;
  min-height: 38px;
}

.spacer {
  flex: 1;
}

.chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  max-width: 150px;
  height: 26px;
  padding: 0 8px;
  border: 0;
  border-radius: 7px;
  background: none;
  color: var(--muted);
  font-size: var(--small);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  transition: background 0.12s, color 0.12s;
}

.chip:hover {
  background: var(--wash-2);
  color: var(--fg);
}

.chip.strong {
  color: var(--fg);
  font-weight: 550;
}

.chip.permission .icon {
  color: var(--tone);
}

.chip.permission.risk-3 .icon {
  filter: drop-shadow(0 0 4px color-mix(in srgb, var(--tone) 70%, transparent));
}

.chip.effort {
  gap: 7px;
}

.chip.effort .pips {
  height: 12px;
}

.chip.effort .fx-flow,
.chip.effort .fx-aurora {
  font-weight: 600;
}

.ctx {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 26px;
  padding: 0 8px 0 6px;
  border: 0;
  border-radius: 999px;
  background: none;
  color: var(--muted);
  font-size: var(--small);
  font-variant-numeric: tabular-nums;
}

.ctx:hover,
.ctx.open {
  background: var(--wash-2);
  color: var(--fg);
}

.ctx.tight {
  color: var(--amber);
}

.ctx.full {
  color: var(--red);
}

.send,
.stop {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  margin-left: 4px;
  padding: 0;
  border: 0;
  border-radius: 50%;
  transition: opacity 0.12s, transform 0.12s, background 0.12s;
}

.send {
  background: var(--fg);
  color: var(--bg);
}

.send:disabled {
  opacity: 0.22;
  cursor: default;
}

.send:not(:disabled):hover {
  transform: scale(1.06);
}

.stop {
  background: color-mix(in srgb, var(--red) 18%, transparent);
  color: var(--red);
}

.stop:hover {
  background: color-mix(in srgb, var(--red) 28%, transparent);
}

.hint {
  flex: 1;
  min-width: 0;
  text-align: right;
  color: var(--faint);
  font-size: 11px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.foot {
  display: flex;
  align-items: baseline;
  gap: 14px;
  padding: 6px 4px 0;
}

.stats {
  display: flex;
  flex-shrink: 0;
  align-items: baseline;
  color: var(--muted);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.stat + .stat::before {
  content: "·";
  margin: 0 7px;
  color: var(--faint);
}

.menu {
  position: absolute;
  left: 0;
  right: 0;
  bottom: calc(100% + 6px);
  max-height: 280px;
  overflow-y: auto;
  padding: 4px;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-m);
  background: var(--raised);
  box-shadow: var(--shadow);
  z-index: 40;
  animation: rise 0.12s ease-out;
}

.menu-item {
  display: flex;
  align-items: baseline;
  gap: 10px;
  width: 100%;
  padding: 6px 9px;
  border: 0;
  border-radius: 6px;
  background: none;
  text-align: left;
}

.menu-item.active {
  background: var(--wash-2);
}

.menu-label {
  flex-shrink: 0;
  font-family: var(--mono);
  font-size: 12.5px;
  font-weight: 600;
}

.menu-desc {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--muted);
  font-size: var(--small);
}
</style>
