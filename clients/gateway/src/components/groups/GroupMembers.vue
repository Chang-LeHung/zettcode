<script setup lang="ts">
import { computed } from "vue";
import { t } from "../../i18n";
import { percent, tokens } from "../../lib/format";
import { usage, useUsage } from "../../stores/usage";
import { href } from "../../stores/route";
import type { Member } from "../../stores/groups";
import { restartable, restartAll, restartNow, restarting } from "../chat/threadActions";
import { restartBlocker } from "../../lib/restart";
import { threadOf } from "../../stores/threads";
import Avatar from "../common/Avatar.vue";
import Icon from "../common/Icon.vue";

const props = defineProps<{ members: Member[]; canInvite?: boolean }>();
defineEmits<{ close: []; invite: []; remove: [member: Member] }>();

// The numbers beside each member come from the Dashboard's read; this sheet asks for them itself rather than depend on
// some other component having done it.
useUsage();

const wordOf = (member: Member): string =>
  member.me ? t("you") : member.status === "working" ? t("typing…") : member.online ? t("online") : t("offline");

/** What a member has spent: its tokens in and out and its cached share. Empty until the numbers are read. */
const spentOf = (member: Member): string => {
  const row = usage.data?.sessions.find((item) => item.id === member.id);
  return row ? `${tokens(row.input_tokens + row.output_tokens)} · ${percent(row.cache_rate)}` : "";
};

/** Each member with its state line decided once, and the stopped daemon that one press can start again, if it is one. */
const rows = computed(() =>
  props.members.map((member) => ({
    member,
    state: [wordOf(member), spentOf(member)].filter(Boolean).join(" · "),
    stopped: !member.online && !member.me ? restartable([member.id])[0] : undefined,
    blocker: !member.online && !member.me && threadOf(member.id)?.kind === "daemon"
      ? restartBlocker(threadOf(member.id)) : undefined,
  })),
);
const stoppedIds = computed(() => rows.value.flatMap(({ stopped }) => stopped ? [stopped.id] : []));
const starting = computed(() => stoppedIds.value.some((id) => restarting.has(id)));
</script>

<template>
  <aside class="members" :aria-label="t('Members')">
    <div class="members-head">
      <b>{{ t("Members") }}</b>
      <span class="members-count">{{ members.length }}</span>
      <button v-if="canInvite" class="iconbtn" :aria-label="t('Invite')" :title="t('Invite')" @click="$emit('invite')">
        <Icon name="plus" size="sm" />
      </button>
      <button class="iconbtn" :aria-label="t('Close')" @click="$emit('close')"><Icon name="close" size="sm" /></button>
    </div>
    <div v-if="stoppedIds.length" class="members-restarts" role="status">
      <span>{{ stoppedIds.length === 1 ? t("{name} is stopped and can be restarted.", { name: rows.find((row) => row.stopped)?.member.name ?? "" }) : t("{count} daemons are stopped and can be restarted.", { count: stoppedIds.length }) }}</span>
      <button class="btn sm" type="button" :disabled="starting" @click="restartAll(stoppedIds)">
        <span v-if="starting" class="spin" />
        <Icon v-else name="refresh" size="sm" />{{ stoppedIds.length === 1 ? t("Restart it") : t("Restart all") }}
      </button>
    </div>
    <ul>
      <li v-for="{ member, state, stopped, blocker } in rows" :key="member.id">
        <component :is="member.chat ? 'a' : 'div'" class="member" :href="member.chat ? href('chats', member.id) : undefined">
          <Avatar
            :thread="{ id: member.id, name: member.name, kind: 'session', status: member.online ? member.status : 'dead' }"
            size="sm"
          />
          <span class="member-body">
            <span class="member-name">{{ member.name }}</span>
            <span class="member-state" :class="{ on: member.online }">{{ state }}</span>
            <span v-if="blocker" class="member-state member-blocker">{{ t(blocker) }}</span>
          </span>
        </component>
        <button
          v-if="stopped"
          class="iconbtn member-restart"
          type="button"
          :disabled="restarting.has(member.id)"
          :aria-label="t('Restart {name}', { name: member.name })"
          :title="t('Restart {name}', { name: member.name })"
          @click="restartNow(stopped)"
        >
          <span v-if="restarting.has(member.id)" class="spin" />
          <Icon v-else name="refresh" size="sm" />
        </button>
        <button
          v-if="canInvite || member.me"
          class="iconbtn member-out"
          type="button"
          :aria-label="member.me ? t('Leave group') : t('Remove from group')"
          :title="member.me ? t('Leave group') : t('Remove from group')"
          @click="$emit('remove', member)"
        >
          <Icon :name="member.me ? 'logout' : 'close'" size="sm" />
        </button>
      </li>
    </ul>
  </aside>
</template>

<style>
.members { flex: none; width: 320px; display: flex; flex-direction: column; background: var(--surface); border-left: 1px solid var(--divider); overflow-y: auto; }
.members-restarts { display: flex; flex-direction: column; align-items: flex-start; gap: 8px; padding: 10px 14px; border-bottom: 1px solid var(--divider); color: var(--muted); font-size: 0.8rem; }
.member-restart { flex: none; width: 34px; height: 34px; color: var(--accent); }
.member-state.member-blocker { color: var(--warn); overflow-wrap: anywhere; }
.members-head { display: flex; align-items: center; gap: 8px; padding: 10px 8px 6px 14px; position: sticky; top: 0; background: var(--surface); }
.members-head b { flex: 1; }
.members-count { color: var(--muted); font-size: 0.85rem; }
.members ul { list-style: none; margin: 0; padding: 0 0 8px; }
.members li { display: flex; align-items: center; padding-right: 6px; }
.members li > .member { flex: 1; min-width: 0; }
.member-out { width: 34px; height: 34px; opacity: 0.55; }
.member-out:hover, .member-out:focus-visible { opacity: 1; color: var(--bad); }
@media (pointer: coarse) { .member-out { opacity: 1; } }
.member { display: flex; align-items: center; gap: 10px; padding: 6px 14px; color: inherit; text-decoration: none !important; }
a.member:hover { background: var(--hover); }
.member-body { min-width: 0; display: flex; flex-direction: column; }
.member-name { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.member-state { font-size: 0.8rem; color: var(--muted); }
.member-state.on { color: var(--ok); }
@media (max-width: 1100px) {
  .members { position: absolute; inset: 0 0 0 auto; width: min(82%, 320px); z-index: 5; box-shadow: var(--shadow); }
  .group-body { position: relative; }
}
</style>
