<script setup lang="ts">
import { computed } from "vue";
import { t } from "../../i18n";
import { go, route } from "../../stores/route";
import { lobby } from "../../stores/threads";
import { chat } from "../../stores/chat";
import { groupArg, groupList, membersOf } from "../../stores/groups";
import type { Thread } from "../../types";
import ConnectionBanner from "../shell/ConnectionBanner.vue";
import PaneHeader from "../shell/PaneHeader.vue";
import GroupRow from "../groups/GroupRow.vue";
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
const shownGroups = computed(() => {
  const needle = search.value.trim().toLowerCase();
  if (!needle) return groupList.value;
  return groupList.value.filter(
    (group) =>
      group.name.toLowerCase().includes(needle) ||
      group.last?.text.toLowerCase().includes(needle) ||
      membersOf(group).some((member) => member.name.toLowerCase().includes(needle)),
  );
});
// The list is already in two runs, the online ones and then the offline ones, each with the latest activity first: say where the second begins.
const daemons = computed(() => shown.value.filter((thread) => thread.kind === "daemon"));
const firstOffline = computed(() => daemons.value.find((thread) => !thread.online)?.id ?? "");
const others = computed(() => shown.value.filter((thread) => thread.kind !== "daemon"));
const open = computed(() => (route.nav === "chats" ? route.arg : chat.id));
</script>

<template>
  <PaneHeader :title="t('Chats')" />
  <SearchBox v-model="search" />
  <ConnectionBanner />
  <div class="pane-list">
    <div v-if="lobby.loaded && !lobby.threads.length && !groupList.length" class="empty">
      <b>{{ t("No sessions yet") }}</b>
      {{ t("Start a daemon, or open a ZettCode session in a terminal, and it appears here.") }}
      <button class="btn" @click="go('new')">{{ t("New daemon") }}</button>
    </div>
    <div v-else-if="!shown.length && !shownGroups.length" class="empty">{{ t("Nothing matches") }}</div>
    <template v-if="shownGroups.length">
      <div class="pane-group">{{ t("Groups") }}</div>
      <GroupRow v-for="group in shownGroups" :key="group.name" :group="group" :current="groupArg(group.name) === open" />
    </template>
    <template v-if="daemons.length">
      <div class="pane-group">{{ t("Daemons") }}</div>
      <template v-for="thread in daemons" :key="thread.id">
        <div v-if="thread.id === firstOffline && firstOffline !== daemons[0]?.id" class="pane-subgroup">{{ t("Offline") }}</div>
        <ChatRow :thread="thread" :current="thread.id === open" />
      </template>
    </template>
    <template v-if="others.length">
      <div class="pane-group">{{ t("Other sessions") }}</div>
      <ChatRow v-for="thread in others" :key="thread.id" :thread="thread" :current="thread.id === open" />
    </template>
  </div>
</template>
