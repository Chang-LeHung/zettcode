<script setup lang="ts">
import { computed, ref } from "vue";
import { t } from "../../i18n";
import { canJoinGroup, inviteToGroup } from "../../stores/groups";
import { lobby } from "../../stores/threads";
import { toast } from "../../stores/ui";
import Avatar from "../common/Avatar.vue";

const props = defineProps<{ group: string; members: string[] }>();
const emit = defineEmits<{ close: [] }>();
const query = ref("");
const busy = ref("");

const held = computed(() => new Set(props.members));
const wanted = computed(() => query.value.trim().toLowerCase());
const matches = (...fields: string[]): boolean =>
  !wanted.value || fields.some((field) => field.toLowerCase().includes(wanted.value));

// An external agent is not offered: two of them in a group would answer each other without end.
const sessions = computed(() =>
  lobby.threads.filter(
    (thread) => canJoinGroup(thread) && !held.value.has(thread.id) && matches(thread.name, thread.title, thread.handle),
  ),
);
const empty = computed(() => !sessions.value.length);

async function invite(id: string): Promise<void> {
  busy.value = id;
  const reason = await inviteToGroup(props.group, id);
  busy.value = "";
  if (reason) {
    toast(reason, "bad");
    return;
  }
  toast(t("Invited"));
  emit("close");
}
</script>

<template>
  <div class="invite">
    <input v-model="query" type="search" :placeholder="t('Search sessions')" :aria-label="t('Search sessions')" />

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
      {{ query.trim() ? t("Nothing matches") : t("No other session can be invited. External agents cannot join a group yet.") }}
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
.invite-copy { min-width: 0; flex: 1; display: flex; flex-direction: column; gap: 1px; }
.invite-copy b, .invite-copy small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.invite-copy small { color: var(--muted); font-size: 0.78rem; }
.invite-add { flex: none; color: var(--accent); font-weight: 600; font-size: 0.82rem; }
</style>
