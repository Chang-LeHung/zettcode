<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { gateway } from "../../api/gateway";
import { ApiError } from "../../api/http";
import { t } from "../../i18n";
import { inviteToGroup } from "../../stores/groups";
import { loadThreads, lobby } from "../../stores/threads";
import { toast } from "../../stores/ui";
import type { AgentType } from "../../types";
import Avatar from "../common/Avatar.vue";

const props = defineProps<{ group: string; members: string[] }>();
const emit = defineEmits<{ close: [] }>();
const query = ref("");
const busy = ref("");
const failure = ref("");
const types = ref<AgentType[]>([]);

onMounted(async () => {
  try {
    types.value = (await gateway.agents()).agents;
  } catch (error) {
    failure.value = error instanceof ApiError ? error.message : String(error);
  }
});

const held = computed(() => new Set(props.members));
const wanted = computed(() => query.value.trim().toLowerCase());
const matches = (...fields: string[]): boolean =>
  !wanted.value || fields.some((field) => field.toLowerCase().includes(wanted.value));

/** A type with a running agent is represented by that agent in the list instead of a second "start" row. */
function anyRunning(type: AgentType): boolean {
  return lobby.threads.some((thread) => thread.agent === type.name);
}

const agentTypes = computed(() =>
  types.value.filter((type) => !anyRunning(type) && matches(type.title, type.description)),
);
const running = computed(() =>
  lobby.threads.filter(
    (thread) => !!thread.agent && !held.value.has(thread.id) && matches(thread.name, thread.title),
  ),
);
const sessions = computed(() =>
  lobby.threads.filter(
    (thread) => !thread.agent && !held.value.has(thread.id) && matches(thread.name, thread.title, thread.handle),
  ),
);
const empty = computed(() => !agentTypes.value.length && !running.value.length && !sessions.value.length);

async function invite(id: string, key = id): Promise<void> {
  busy.value = key;
  const reason = await inviteToGroup(props.group, id);
  busy.value = "";
  if (reason) {
    toast(reason, "bad");
    return;
  }
  toast(t("Invited"));
  emit("close");
}

async function start(type: AgentType): Promise<void> {
  busy.value = type.name;
  try {
    await gateway.createAgent({ kind: type.name, title: type.title, group: props.group });
    // The agent and its membership are already committed here; a failed list refresh must not say otherwise.
    await loadThreads().catch(() => {});
    toast(t("Invited"));
    emit("close");
  } catch (error) {
    toast(error instanceof ApiError ? error.message : String(error), "bad");
  } finally {
    busy.value = "";
  }
}
</script>

<template>
  <div class="invite">
    <input v-model="query" type="search" :placeholder="t('Search sessions or agents')" :aria-label="t('Search sessions or agents')" />
    <p v-if="failure" class="errcard" role="alert">{{ failure }}</p>

    <template v-if="agentTypes.length">
      <div class="invite-group">{{ t("External agents") }}</div>
      <button
        v-for="type in agentTypes"
        :key="type.name"
        type="button"
        class="invite-row"
        :disabled="busy === type.name"
        @click="start(type)"
      >
        <img v-if="type.avatar" class="invite-logo" :src="type.avatar" alt="" />
        <span v-else class="invite-logo fallback">{{ type.title.slice(0, 1) }}</span>
        <span class="invite-copy">
          <b>{{ type.title }}</b>
          <small>{{ type.description }}</small>
        </span>
        <span class="invite-add">
          {{ busy === type.name ? "…" : t("Start & invite") }}
        </span>
      </button>
    </template>

    <template v-if="running.length">
      <div class="invite-group">{{ t("Running agents") }}</div>
      <button v-for="thread in running" :key="thread.id" type="button" class="invite-row" :disabled="busy === thread.id" @click="invite(thread.id)">
        <Avatar :thread="thread" size="sm" />
        <span class="invite-copy">
          <b>{{ thread.name }}</b>
          <small>{{ thread.title || t("External agent") }}</small>
        </span>
        <span class="invite-add">{{ busy === thread.id ? "…" : t("Invite") }}</span>
      </button>
    </template>

    <template v-if="sessions.length">
      <div class="invite-group">{{ t("Sessions") }}</div>
      <button v-for="thread in sessions" :key="thread.id" type="button" class="invite-row" :disabled="busy === thread.id" @click="invite(thread.id)">
        <Avatar :thread="thread" size="sm" />
        <span class="invite-copy">
          <b>{{ thread.name }}</b>
          <small>{{ thread.kind }}<template v-if="thread.online"> · {{ t("online") }}</template></small>
        </span>
        <span class="invite-add">{{ busy === thread.id ? "…" : t("Invite") }}</span>
      </button>
    </template>

    <div v-if="empty" class="empty">
      {{ query.trim() ? t("Nothing matches") : t("Everyone here is already in the group.") }}
    </div>
  </div>
</template>

<style>
.invite { display: flex; flex-direction: column; gap: 4px; padding: 4px 14px 14px; }
.invite input { min-height: 42px; margin-bottom: 4px; padding: 8px 12px; border: 1px solid var(--divider); border-radius: 11px; outline: none; background: var(--bg); color: var(--text); font: inherit; transition: border-color 0.15s, box-shadow 0.15s; }
.invite input:focus { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
.invite-group { padding: 10px 6px 2px; color: var(--muted); font-size: 0.76rem; font-weight: 650; letter-spacing: 0.03em; text-transform: uppercase; }
.invite-row { display: flex; align-items: center; gap: 10px; width: 100%; padding: 8px 6px; border: 0; border-radius: 10px; background: none; color: inherit; text-align: left; }
.invite-row:hover { background: var(--hover); }
.invite-row:disabled { opacity: 0.6; }
.invite-logo { width: 36px; height: 36px; border-radius: 10px; flex: none; object-fit: cover; background: var(--surface-2); }
.invite-logo.fallback { display: grid; place-items: center; color: var(--accent); font-weight: 700; background: var(--accent-soft); }
.invite-copy { min-width: 0; flex: 1; display: flex; flex-direction: column; gap: 1px; }
.invite-copy b, .invite-copy small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.invite-copy small { color: var(--muted); font-size: 0.78rem; }
.invite-add { flex: none; color: var(--accent); font-weight: 600; font-size: 0.82rem; }
</style>
