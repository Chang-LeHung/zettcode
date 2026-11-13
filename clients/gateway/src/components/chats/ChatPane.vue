<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { t } from "../../i18n";
import { attachPull, THRESHOLD, type Pull } from "../../lib/pull";
import { go, route } from "../../stores/route";
import { loadThreads, lobby } from "../../stores/threads";
import { loadGraph } from "../../stores/graph";
import { chat } from "../../stores/chat";
import { groupArg, groupList, membersOf } from "../../stores/groups";
import type { Thread } from "../../types";
import ConnectionBanner from "../shell/ConnectionBanner.vue";
import PaneHeader from "../shell/PaneHeader.vue";
import GroupRow from "../groups/GroupRow.vue";
import ChatRow from "./ChatRow.vue";
import Icon from "../common/Icon.vue";
import NewGroupSheet from "../groups/NewGroupSheet.vue";
import { openSheet, toast } from "../../stores/ui";
import SearchBox from "./SearchBox.vue";
import Skeleton from "../common/Skeleton.vue";
import { search } from "./search";

const matches = (thread: Thread, needle: string): boolean =>
  [thread.name, thread.title, thread.workspace, thread.id, thread.handle, thread.preview].some((field) =>
    field.toLowerCase().includes(needle),
  );

const searching = computed(() => search.value.trim() !== "");
const matched = computed(() => {
  const needle = search.value.trim().toLowerCase();
  return needle ? lobby.threads.filter((thread) => matches(thread, needle)) : lobby.threads;
});
// An archived conversation is out of the list until it is searched for, or Archived is opened.
const shown = computed(() => (searching.value ? matched.value : matched.value.filter((thread) => !thread.archived)));
const archived = computed(() => (searching.value ? [] : lobby.threads.filter((thread) => thread.archived)));
const showArchived = ref(false);
const pinned = computed(() => shown.value.filter((thread) => thread.pinned && !thread.archived));
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
const rest = computed(() => shown.value.filter((thread) => !pinned.value.includes(thread)));
const daemons = computed(() => rest.value.filter((thread) => thread.kind === "daemon"));
const firstOffline = computed(() => daemons.value.find((thread) => !thread.online)?.id ?? "");
const others = computed(() => rest.value.filter((thread) => thread.kind !== "daemon"));
const open = computed(() => (route.nav === "chats" ? route.arg : chat.id));

// Pull the list down on a phone to read it again, which is what a person does when it looks out of date.
const list = ref<HTMLElement | null>(null);
const pull = ref<Pull | null>(null);
const refreshing = ref(false);
const indicator = computed(() => (refreshing.value ? THRESHOLD / 2 : (pull.value?.distance ?? 0)));
let detach: (() => void) | undefined;
onMounted(() => {
  if (!list.value) return;
  detach = attachPull(list.value, {
    change: (next) => (pull.value = next),
    refresh: async () => {
      refreshing.value = true;
      try {
        await Promise.all([loadThreads(), loadGraph()]);
      } catch {
        toast(t("Could not refresh."), "bad");
      } finally {
        refreshing.value = false;
      }
    },
  });
});
onBeforeUnmount(() => detach?.());
</script>

<template>
  <PaneHeader :title="t('Chats')">
    <button class="iconbtn" :aria-label="t('New group')" :title="t('New group')" @click="openSheet(t('New group'), NewGroupSheet)">
      <Icon name="users" />
    </button>
  </PaneHeader>
  <SearchBox v-model="search" />
  <ConnectionBanner />
  <div ref="list" class="pane-list" :class="{ pulling: pull !== null }">
    <div class="pull-indicator" :style="{ height: `${indicator}px` }" aria-hidden="true">
      <span v-if="refreshing" class="spin" /><Icon v-else-if="indicator > 0" name="chevron" size="sm" :class="{ ready: pull?.ready }" />
    </div>
    <Skeleton v-if="!lobby.loaded" kind="rows" :count="8" />
    <div v-else-if="!lobby.threads.length && !groupList.length" class="empty empty-card">
      <b>{{ t("No sessions yet") }}</b>
      {{ t("Start a daemon, an external agent, or open a ZettCode session in a terminal, and it appears here.") }}
      <button class="btn" @click="go('new')">{{ t("New session") }}</button>
    </div>
    <div v-else-if="!shown.length && !shownGroups.length && !archived.length" class="empty">{{ t("Nothing matches") }}</div>
    <template v-if="pinned.length">
      <div class="pane-group">{{ t("Pinned") }}</div>
      <ChatRow v-for="thread in pinned" :key="thread.id" :thread="thread" :current="thread.id === open" />
    </template>
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
    <template v-if="archived.length">
      <button class="pane-group pane-toggle" type="button" :aria-expanded="showArchived" @click="showArchived = !showArchived">
        <Icon name="archive" size="xs" />{{ t("Archived") }} · {{ archived.length }}
        <Icon class="pane-chevron" :class="{ open: showArchived }" name="chevron" size="xs" />
      </button>
      <template v-if="showArchived">
        <ChatRow v-for="thread in archived" :key="thread.id" :thread="thread" :current="thread.id === open" />
      </template>
    </template>
  </div>
</template>

<style>
.pull-indicator { flex: none; display: flex; align-items: center; justify-content: center; overflow: hidden; color: var(--muted); }
.pane-list:not(.pulling) .pull-indicator { transition: height 0.18s ease; }
.pull-indicator svg { transform: rotate(90deg); transition: transform 0.15s ease, color 0.15s ease; }
.pull-indicator svg.ready { color: var(--accent); transform: rotate(-90deg); }
.pane-list { overscroll-behavior-y: contain; }
.pane-toggle { display: flex; align-items: center; gap: 6px; width: 100%; text-align: left; color: var(--muted); }
.pane-toggle .pane-chevron { margin-left: auto; transition: transform 0.18s ease; }
.pane-toggle .pane-chevron.open { transform: rotate(90deg); }
</style>
