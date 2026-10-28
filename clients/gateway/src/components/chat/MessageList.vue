<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { t } from "../../i18n";
import { buildRows } from "../../lib/rows";
import { chat, loadEarlier } from "../../stores/chat";
import Icon from "../common/Icon.vue";
import MessageBubble from "./MessageBubble.vue";
import NoteBubble from "./NoteBubble.vue";
import StepsGroup from "./StepsGroup.vue";
import { streams } from "../../stores/stream";
import LiveTurn from "./LiveTurn.vue";
import TypingBubble from "./TypingBubble.vue";

const scroller = ref<HTMLElement | null>(null);
const following = ref(true);
const unseen = ref(0);
const rows = computed(() => buildRows(chat.items, chat.pending));
const live = computed(() => streams[chat.id]);
const typing = computed(() => chat.thread?.status === "working" && !live.value);

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

function onScroll(): void {
  following.value = nearBottom();
  if (following.value) unseen.value = 0;
}

watch(
  () => chat.id,
  () => {
    first = true;
    seen = 0;
    unseen.value = 0;
    following.value = true;
  },
);

watch(
  () => chat.revision,
  () => {
    const count = rows.value.length;
    const last = rows.value[count - 1];
    const mine = last?.type === "bubble" && last.pending && last.key !== lastKey;
    lastKey = last?.key ?? "";
    if (first || following.value || mine) {
      toBottom(!first);
      following.value = true;
      first = first && count === 0;
    } else if (count > seen) {
      unseen.value += count - seen;
    }
    seen = count;
  },
  { flush: "post" },
);

watch(typing, (now) => now && following.value && toBottom(true), { flush: "post" });
// A turn that is being written grows the page: stay with it while the person is at the bottom.
watch(
  () => [live.value?.text.length, live.value?.tools.length],
  () => following.value && toBottom(false),
  { flush: "post" },
);
onMounted(() => toBottom(false));
</script>

<template>
  <div class="chat-bg">
    <div ref="scroller" class="messages" role="log" aria-live="polite" @scroll.passive="onScroll">
      <div v-if="chat.loading && !chat.items.length" class="messages-note"><span class="spin" /></div>
      <div v-else-if="chat.error" class="errcard">{{ chat.error }}</div>
      <button v-if="chat.truncated" class="btn sm ghost messages-more" @click="loadEarlier">
        {{ t("Show earlier messages") }}
      </button>
      <template v-for="row in rows" :key="row.key">
        <MessageBubble v-if="row.type === 'bubble'" :row="row" :thread="chat.id" />
        <StepsGroup v-else-if="row.type === 'steps'" :tools="row.tools" />
        <NoteBubble v-else :text="row.text" />
      </template>
      <LiveTurn />
      <TypingBubble v-if="typing" />
      <div v-if="!chat.loading && !rows.length && !chat.error && !live" class="messages-note">{{ t("No messages yet. Say something.") }}</div>
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
  display: flex; flex-direction: column;
}
.messages-note { align-self: center; margin: 12px 0; padding: 4px 14px; border-radius: 14px; background: var(--chip-bg); color: #fff; font-size: 0.85rem; }
.messages-more { align-self: center; margin: 4px 0 10px; }
.fab {
  position: absolute; right: calc(var(--safe-right) + 14px); bottom: 12px; width: 44px; height: 44px; border-radius: 50%;
  display: grid; place-items: center; background: var(--surface); color: var(--muted); box-shadow: 0 2px 10px rgba(0, 0, 0, 0.25);
}
.fab .badge { position: absolute; top: -9px; left: 50%; transform: translateX(-50%); }
</style>
