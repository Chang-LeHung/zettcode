<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { t } from "../../i18n";
import Skeleton from "../common/Skeleton.vue";
import { buildRows } from "../../lib/rows";
import { lineRow } from "../../lib/unread";
import { chat, loadEarlier, markRead } from "../../stores/chat";
import { currentKey, find, search } from "../../stores/chatSearch";
import Icon from "../common/Icon.vue";
import MessageBubble from "./MessageBubble.vue";
import NoteBubble from "./NoteBubble.vue";
import StepsGroup from "./StepsGroup.vue";
import { streams } from "../../stores/stream";
import LiveTurn from "./LiveTurn.vue";
import TypingBubble from "./TypingBubble.vue";

const scroller = ref<HTMLElement | null>(null);
const body = ref<HTMLElement | null>(null);
const following = ref(true);
const unseen = ref(0);
const rows = computed(() => buildRows(chat.items, chat.pending, streams[chat.id]));
const live = computed(() => streams[chat.id]);
const typing = computed(() => chat.thread?.status === "working" && !live.value);
/** The row the unread line goes above: the first row drawn from the item the unread stretch begins at. */
const unreadRow = computed(() => lineRow(rows.value, chat.unreadFrom));

let seen = 0;
let first = true;
let lastKey = "";

function nearBottom(): boolean {
  const el = scroller.value;
  return !el || el.scrollHeight - el.scrollTop - el.clientHeight < 140;
}

function toBottom(smooth: boolean): void {
  void nextTick(() => scroller.value?.scrollTo({ top: scroller.value.scrollHeight, behavior: smooth ? "smooth" : "auto" }));
}

/** Put the unread line eight pixels below the top edge, so the reader sees at once what is new and where it begins. */
function placeLine(): void {
  const el = scroller.value;
  if (!el) return;
  const line = el.querySelector<HTMLElement>(".messages-line");
  if (!line) return;
  const top = el.scrollTop + line.getBoundingClientRect().top - el.getBoundingClientRect().top - 8;
  el.scrollTo({ top: Math.max(0, top), behavior: "auto" });
  // Where the reader now is, so that a scroll of theirs is told from this one.
  placedAt = el.scrollTop;
}

/** Stop on the unread line, as a messenger does, rather than at the newest message. */
function toUnread(): void {
  void nextTick(() => {
    following.value = false;
    chat.atBottom = false;
    placeLine();
    // What is above the line is still being drawn (a message growing as it is laid out), and the list keeps the
    // reader where they are only while this says so: it is what a browser's own scroll anchoring would do.
    aligning = Date.now();
  });
}

function onScroll(): void {
  // A reader who has started moving the list themselves is not to be pulled back to the line while the content above
  // it settles: the realign is for growth nobody asked for.
  if (aligning && Math.abs((scroller.value?.scrollTop ?? 0) - placedAt) > 2) aligning = 0;
  following.value = nearBottom();
  chat.atBottom = following.value;
  if (following.value) {
    unseen.value = 0;
    if (!document.hidden) markRead();
  }
}

watch(
  () => chat.id,
  () => {
    first = true;
    seen = 0;
    unseen.value = 0;
    following.value = true;
    chat.atBottom = true;
  },
);

watch(
  () => chat.revision,
  () => {
    const count = rows.value.length;
    const last = rows.value[count - 1];
    const mine = last?.type === "bubble" && last.pending && last.key !== lastKey;
    lastKey = last?.key ?? "";
    if (first && count > 0 && chat.unreadFrom !== null) {
      // Opened on a conversation with something unread: stop where the reader left off, not at the newest message.
      toUnread();
      first = false;
    } else if (first || following.value || mine) {
      toBottom(!first);
      following.value = true;
      chat.atBottom = true;
      first = first && count === 0;
    } else if (count > seen) {
      unseen.value += count - seen;
    }
    seen = count;
  },
  { flush: "post" },
);

watch(typing, (now) => now && following.value && toBottom(true), { flush: "post" });
// The search looks again whenever the words, or what there is to look in, change.
watch([rows, () => find.query, () => find.open], () => find.open && search(rows.value), { flush: "post" });
// The match the reader is on is brought to the middle of the page, and the page stops following the newest message.
watch(
  currentKey,
  (key) => {
    if (!key) return;
    following.value = false;
    const target = scroller.value?.querySelector(`[data-row="${key}"]`);
    target?.scrollIntoView({ block: "center", behavior: "smooth" });
  },
  { flush: "post" },
);
// With the bar closed the page follows the newest message again if the reader is at the bottom, as it did before the search.
watch(
  () => find.open,
  (open) => {
    if (!open) following.value = nearBottom();
  },
);
// A turn that is being written grows the page: stay with it while the person is at the bottom.
watch(
  () => [live.value?.text.length, live.value?.tools.length],
  () => following.value && toBottom(false),
  { flush: "post" },
);
// The keyboard rising or falling changes the height of the list: stay at the newest message, as a messenger does.
function onViewport(): void {
  if (following.value) toBottom(false);
}
// What is inside a message grows after it is drawn (markdown, code, images, a font arriving), and nothing else moves
// the list then: stay at the newest message for as long as the reader is following it, and leave a reader who scrolled
// up alone. Each step is instant, so there is nothing to chase.
let watcher: ResizeObserver | undefined;
/** When the reader was put on the unread line, and how long growing content keeps them there. */
let aligning = 0;
/** Where the line was last placed, so that a scroll of the reader's is told apart from one of ours. */
let placedAt = 0;
const ALIGNING_MS = 1200;
onMounted(() => {
  toBottom(false);
  window.visualViewport?.addEventListener("resize", onViewport);
  if (body.value && typeof ResizeObserver !== "undefined") {
    watcher = new ResizeObserver(() => {
      if (aligning && Date.now() - aligning < ALIGNING_MS) placeLine();
      else if (following.value) toBottom(false);
    });
    watcher.observe(body.value);
  }
});
onBeforeUnmount(() => {
  window.visualViewport?.removeEventListener("resize", onViewport);
  watcher?.disconnect();
});
</script>

<template>
  <div class="chat-bg">
    <div ref="scroller" class="messages" role="log" aria-live="polite" @scroll.passive="onScroll">
      <div ref="body" class="messages-body">
        <Skeleton v-if="chat.loading && !chat.items.length" kind="bubbles" :count="7" />
        <div v-else-if="chat.error" class="errcard">{{ chat.error }}</div>
        <button v-if="chat.truncated" class="btn sm ghost messages-more" :disabled="chat.loadingEarlier" @click="loadEarlier">
          <span v-if="chat.loadingEarlier" class="spin" />{{ t("Show earlier messages") }}
        </button>
        <template v-for="row in rows" :key="row.key">
          <div v-if="row === unreadRow" class="messages-line">{{ t("New messages") }}</div>
          <MessageBubble v-if="row.type === 'bubble'" :row="row" :thread="chat.id" />
          <StepsGroup v-else-if="row.type === 'steps'" :tools="row.tools" />
          <NoteBubble v-else :text="row.text" />
        </template>
        <LiveTurn />
        <TypingBubble v-if="typing" />
        <div v-if="!chat.loading && !rows.length && !chat.error && !live" class="messages-note">{{ t("No messages yet. Say something.") }}</div>
      </div>
    </div>
    <button v-show="!following" class="fab" :aria-label="t('Scroll to the newest message')" @click="toBottom(true)">
      <Icon name="down" />
      <span v-if="unseen" class="badge">{{ unseen }}</span>
    </button>
  </div>
</template>

<style>
.chat-bg {
  flex: 1; position: relative; min-height: 0; display: flex; flex-direction: column;
  background: var(--chat-bg-a);
}
.messages {
  flex: 1; overflow-y: auto; overscroll-behavior: contain; -webkit-overflow-scrolling: touch;
  padding: 12px calc(var(--safe-right) + 14px) 10px calc(var(--safe-left) + 14px);
  display: flex; flex-direction: column; overflow-anchor: none;
}
.messages-body { display: flex; flex-direction: column; flex: none; }
.messages-note { align-self: center; margin: 12px 0; padding: 4px 14px; border-radius: 14px; background: var(--chip-bg); color: #fff; font-size: 0.85rem; }
.messages-more { align-self: center; margin: 4px 0 10px; }
.messages-line {
  align-self: center; margin: 8px 0 4px; padding: 3px 12px; border-radius: 12px;
  background: var(--chip-bg); color: #fff; font-size: 0.78rem; letter-spacing: 0.02em;
}
.fab {
  position: absolute; right: calc(var(--safe-right) + 14px); bottom: 12px; width: 44px; height: 44px; border-radius: 50%;
  display: grid; place-items: center; background: var(--surface); color: var(--muted); box-shadow: 0 2px 10px rgba(0, 0, 0, 0.25);
  animation: pop 0.22s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.fab .badge { position: absolute; top: -9px; left: 50%; transform: translateX(-50%); }
</style>
