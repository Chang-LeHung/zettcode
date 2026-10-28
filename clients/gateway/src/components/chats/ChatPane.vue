<script setup lang="ts">
import { computed } from "vue";
import { t } from "../../i18n";
import { go, route } from "../../stores/route";
import { lobby } from "../../stores/threads";
import { chat } from "../../stores/chat";
import type { Thread } from "../../types";
import ConnectionBanner from "../shell/ConnectionBanner.vue";
import PaneHeader from "../shell/PaneHeader.vue";
import ChatRow from "./ChatRow.vue";
import SearchBox from "./SearchBox.vue";
import { search } from "./search";

const matches = (thread: Thread, needle: string): boolean =>
  [thread.name, thread.title, thread.workspace, thread.id, thread.handle, thread.preview].some((field) =>
    field.toLowerCase().includes(needle),
  );

const shown = computed(() => {
  const needle = search.value.trim().toLowerCase();
  return needle ? lobby.threads.filter((thread) => matches(thread, needle)) : lobby.threads;
});
const daemons = computed(() => shown.value.filter((thread) => thread.kind === "daemon"));
const others = computed(() => shown.value.filter((thread) => thread.kind !== "daemon"));
const open = computed(() => (route.nav === "chats" ? route.arg : chat.id));
</script>

<template>
  <PaneHeader :title="t('Chats')" />
  <SearchBox v-model="search" />
  <ConnectionBanner />
  <div class="pane-list">
    <div v-if="lobby.loaded && !lobby.threads.length" class="empty">
      <b>{{ t("No sessions yet") }}</b>
      {{ t("Start a daemon, or open a ZettCode session in a terminal, and it appears here.") }}
      <button class="btn" @click="go('new')">{{ t("New daemon") }}</button>
    </div>
    <div v-else-if="!shown.length" class="empty">{{ t("Nothing matches") }}</div>
    <template v-if="daemons.length">
      <div class="pane-group">{{ t("Daemons") }}</div>
      <ChatRow v-for="thread in daemons" :key="thread.id" :thread="thread" :current="thread.id === open" />
    </template>
    <template v-if="others.length">
      <div class="pane-group">{{ t("Other sessions") }}</div>
      <ChatRow v-for="thread in others" :key="thread.id" :thread="thread" :current="thread.id === open" />
    </template>
  </div>
</template>
