<script setup lang="ts">
import { t } from "../../i18n";
import { href } from "../../stores/route";
import type { Member } from "../../stores/groups";
import Avatar from "../common/Avatar.vue";
import Icon from "../common/Icon.vue";

defineProps<{ members: Member[]; canInvite?: boolean }>();
defineEmits<{ close: []; invite: []; remove: [member: Member] }>();

const word = (member: Member): string =>
  member.me ? t("you") : member.status === "working" ? t("typing…") : member.online ? t("online") : t("offline");
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
    <ul>
      <li v-for="member in members" :key="member.id">
        <component :is="member.chat ? 'a' : 'div'" class="member" :href="member.chat ? href('chats', member.id) : undefined">
          <Avatar
            :thread="{ id: member.id, name: member.name, kind: 'session', status: member.online ? member.status : 'dead' }"
            size="sm"
          />
          <span class="member-body">
            <span class="member-name">{{ member.name }}</span>
            <span class="member-state" :class="{ on: member.online }">{{ word(member) }}</span>
          </span>
        </component>
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
.members { flex: none; width: 260px; display: flex; flex-direction: column; background: var(--surface); border-left: 1px solid var(--divider); overflow-y: auto; }
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
@media (max-width: 719px) {
  .members { position: absolute; inset: 56px 0 0 auto; width: min(82vw, 320px); z-index: 5; box-shadow: var(--shadow); }
  .group-body { position: relative; }
}
</style>
