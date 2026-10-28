<script setup lang="ts">
import { computed } from "vue";
import { t } from "../../i18n";
import type { Row } from "../../lib/rows";
import { dismiss, retry, wantsReply } from "../../stores/chat";
import { threadOf } from "../../stores/threads";
import Avatar from "../common/Avatar.vue";
import Icon from "../common/Icon.vue";
import UserAvatar from "../common/UserAvatar.vue";
import MessageText from "./MessageText.vue";

type BubbleRow = Extract<Row, { type: "bubble" }>;
const props = defineProps<{ row: BubbleRow; thread: string }>();

const owner = computed(() => threadOf(props.thread));
// Only a message from another session says who it is from: what you typed needs no label.
const who = computed(() => {
  const item = props.row.item;
  return item.kind === "from" ? `${item.sender} · ${item.via}` : "";
});
const state = computed(() => props.row.pending?.state ?? "stored");
const failure = computed(() => props.row.pending?.error);

function again(): void {
  const entry = props.row.pending;
  const thread = threadOf(props.thread);
  if (entry && thread) void retry(entry, wantsReply(thread));
}
</script>

<template>
  <div class="msg" :class="[row.side, { cont: row.cont }]">
    <template v-if="row.side === 'in'">
      <Avatar v-if="row.tail && owner" class="msg-avatar" :thread="owner" size="sm" />
      <div v-else class="msg-avatar" />
    </template>
    <div class="bubble" :class="{ reply: row.item.kind === 'reply', err: state === 'failed' }">
      <span v-if="who" class="bubble-who">{{ who }}</span>
      <MessageText :text="row.item.text" />
      <span v-if="state === 'sending' || state === 'queued' || state === 'failed'" class="meta">
        <span v-if="state === 'queued'">{{ t("queued") }}</span>
        <Icon v-if="state === 'sending'" name="clock" size="xs" />
        <Icon v-else-if="state === 'failed'" class="meta-bad" name="warn" size="xs" />
      </span>
      <div v-if="failure" class="bubble-retry">
        <span class="bubble-why">
          {{ failure.message }}
          <template v-if="failure.uncertain"> {{ t("It may or may not have arrived; sending again could duplicate it.") }}</template>
        </span>
        <button class="btn sm" @click="again">{{ t("Send again") }}</button>
        <button class="btn sm ghost" @click="row.pending && dismiss(row.pending)">{{ t("Delete") }}</button>
      </div>
    </div>
    <template v-if="row.side === 'out'">
      <UserAvatar v-if="row.tail" class="msg-avatar" size="sm" />
      <div v-else class="msg-avatar" />
    </template>
  </div>
</template>

<style>
.msg { display: flex; align-items: flex-start; gap: 8px; max-width: 100%; margin-top: 12px; }
.msg.out { justify-content: flex-end; }
.msg.out.cont { margin-top: 3px; }
.msg-avatar { flex: none; width: 40px; height: 40px; }
.bubble {
  position: relative; min-width: 0; max-width: min(78%, 34rem); padding: 7px 11px 6px; border-radius: var(--bubble-radius);
  box-shadow: var(--shadow); line-height: 1.38; overflow-wrap: anywhere; word-break: break-word; animation: pop 0.16s ease-out;
}
.msg.in .bubble { max-width: min(92%, 52rem); padding: 9px 14px 8px; background: var(--in-bubble); color: var(--in-text); border-bottom-left-radius: 6px; }
.msg.out .bubble { background: var(--out-bubble); color: var(--out-text); border-bottom-right-radius: 6px; }
.msg.out.cont .bubble { border-top-right-radius: 6px; }
.msg.out .bubble a, .msg.out .bubble .md a { color: #fff; }
.msg.out .bubble .md code { background: rgba(255, 255, 255, 0.2); }
.msg.out .bubble .md blockquote { color: rgba(255, 255, 255, 0.8); border-color: rgba(255, 255, 255, 0.6); }
.msg.out .bubble .msg-code { background: rgba(255, 255, 255, 0.2); }
.bubble.reply { box-shadow: var(--shadow), inset 3px 0 0 var(--accent); }
.bubble.err { box-shadow: var(--shadow), inset 0 0 0 1px var(--bad); }
.bubble-who { display: block; font-size: 0.8rem; font-weight: 600; color: rgba(255, 255, 255, 0.85); margin-bottom: 2px; }
.meta { display: inline-flex; align-items: center; gap: 3px; float: right; margin: 5px 0 -2px 10px; font-size: 0.72rem; color: var(--out-meta); user-select: none; }
.meta-read { color: var(--out-meta); }
.meta-bad { color: var(--bad); }
.bubble-retry { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-top: 8px; clear: both; }
.bubble-why { flex-basis: 100%; font-size: 0.82rem; color: #fff; line-height: 1.35; }
@media (max-width: 719px) {
  .msg { gap: 6px; }
  .msg-avatar { width: 32px; height: 32px; }
  .msg.in .bubble { max-width: calc(100% - 38px); }
  .msg.out .bubble { max-width: calc(86% - 38px); }
}
</style>
