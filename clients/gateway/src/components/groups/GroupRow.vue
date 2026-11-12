<script setup lang="ts">
import { computed } from "vue";
import { t } from "../../i18n";
import { listTime } from "../../lib/format";
import { badge } from "../../lib/unread";
import { href } from "../../stores/route";
import { groupArg, senderName, unreadOf } from "../../stores/groups";
import type { GraphGroup } from "../../types";
import Avatar from "../common/Avatar.vue";
import Icon from "../common/Icon.vue";

const props = defineProps<{ group: GraphGroup; current: boolean }>();

const unread = computed(() => unreadOf(props.group.name));
/** One line of plain text: who said it, and what. */
const plainLine = (text: string): string =>
  text.replace(/```[\w+#.-]*/g, " ").replace(/[`*_#>]+/g, "").replace(/\s+/g, " ").trim();
const line = computed(() => {
  const last = props.group.last;
  if (!last) {
    return props.group.members.length === 1
      ? t("1 member")
      : t("{count} members", { count: props.group.members.length });
  }
  const who = senderName(last);
  return `${who ? `${who}: ` : `${t("You")}: `}${plainLine(last.text)}`;
});
</script>

<template>
  <a class="row" :href="href('chats', groupArg(group.name))" :aria-current="current ? 'true' : undefined">
    <Avatar :thread="{ id: `#${group.name}`, name: group.name, kind: 'external', status: 'idle' }" />
    <div class="row-body">
      <div class="row-top">
        <Icon class="row-kind" name="users" size="xs" />
        <span class="row-name">{{ group.name }}</span>
        <span class="row-time">{{ listTime(group.last?.ts ?? group.created) }}</span>
      </div>
      <div class="row-bottom">
        <span class="row-sub">{{ line }}</span>
        <span v-if="unread" class="badge">{{ badge(unread) }}</span>
      </div>
    </div>
  </a>
</template>
