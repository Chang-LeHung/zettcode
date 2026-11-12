<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, watch } from "vue";
import { t } from "../../i18n";
import { chat, closeChat, markRead, openChat } from "../../stores/chat";
import { canWrite, threadOf } from "../../stores/threads";
import Skeleton from "../common/Skeleton.vue";
import ChatHeader from "./ChatHeader.vue";
import Composer from "./Composer.vue";
import LockedBar from "./LockedBar.vue";
import MessageList from "./MessageList.vue";

const props = defineProps<{ id: string }>();

const thread = computed(() => threadOf(props.id) ?? (chat.id === props.id ? chat.thread : null));
const missing = computed(() => !thread.value && !chat.loading && chat.id === props.id && chat.error !== "");

watch(() => props.id, (id) => void openChat(id), { immediate: true });
watch(
  () => thread.value?.unread ?? 0,
  (unread) => unread > 0 && !document.hidden && markRead(),
);
// Back at the bottom: what was above is read now.
watch(() => chat.atBottom, (bottom) => bottom && !document.hidden && markRead());

function onVisible(): void {
  if (!document.hidden) markRead();
}
onMounted(() => document.addEventListener("visibilitychange", onVisible));
onBeforeUnmount(() => {
  document.removeEventListener("visibilitychange", onVisible);
  closeChat();
});
</script>

<template>
  <div v-if="missing" class="empty">
    <b>{{ t("This session is not listed") }}</b>
    {{ chat.error }}
  </div>
  <div v-else-if="thread" class="chat">
    <ChatHeader :thread="thread" />
    <MessageList />
    <Composer v-if="canWrite(thread)" :thread="thread" />
    <LockedBar v-else :thread="thread" />
  </div>
  <Skeleton v-else kind="bubbles" :count="6" />
</template>

<style>
.chat { flex: 1; min-height: 0; display: flex; flex-direction: column; }
</style>
