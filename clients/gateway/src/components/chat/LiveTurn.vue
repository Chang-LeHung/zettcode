<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { settleLive } from "../../lib/rows";
import { chat } from "../../stores/chat";
import { streams } from "../../stores/stream";
import { threadOf } from "../../stores/threads";
import Avatar from "../common/Avatar.vue";
import MessageText from "./MessageText.vue";
import TypingBubble from "./TypingBubble.vue";

const turn = computed(() => streams[chat.id]);

// The answer is drawn as markdown, which is parsed whole each time: a long one is not re-drawn at every piece the
// gateway sends but a few times a second, and the last piece always lands.
const RENDER_EVERY_MS = 250;
const shown = ref("");
let last = 0;
let timer: number | undefined;
function sync(): void {
  timer = undefined;
  last = Date.now();
  shown.value = turn.value?.text ?? "";
}
// A new turn starts from nothing, not from the last one's words.
watch(turn, () => {
  window.clearTimeout(timer);
  timer = undefined;
  shown.value = "";
});
watch(
  () => turn.value?.text,
  () => {
    if (timer === undefined) timer = window.setTimeout(sync, Math.max(0, RENDER_EVERY_MS - (Date.now() - last)));
  },
  { immediate: true },
);
onBeforeUnmount(() => window.clearTimeout(timer));
const owner = computed(() => threadOf(chat.id));
// The tools are drawn with the stored steps (see `buildRows`), so that a turn is one group of steps. What is drawn here
// is the answer so far, less what the conversation already holds.
const fresh = computed(() => (turn.value ? settleLive(chat.items, { ...turn.value, text: shown.value }).text : ""));
</script>

<template>
  <template v-if="turn">
    <div v-if="fresh" class="msg in live">
      <Avatar v-if="owner" class="msg-avatar" :thread="owner" size="sm" />
      <div class="bubble">
        <MessageText :text="fresh" />
      </div>
    </div>
    <TypingBubble v-else />
  </template>
</template>
