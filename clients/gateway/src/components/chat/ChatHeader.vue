<script setup lang="ts">
import { computed } from "vue";
import { t } from "../../i18n";
import { folderName } from "../../lib/format";
import { prefs } from "../../stores/prefs";
import { href } from "../../stores/route";
import type { Thread } from "../../types";
import Avatar from "../common/Avatar.vue";
import Icon from "../common/Icon.vue";
import { showInfo, showThreadMenu } from "./threadActions";

const props = defineProps<{ thread: Thread }>();

/** How a message to this session is delivered, which is not otherwise visible. */
const mode = computed(() => {
  const thread = props.thread;
  if (thread.locked) return { label: t("Busy elsewhere"), hint: t("Another window has this session open, so it is read-only here."), kind: "bad" };
  if (!thread.online) return null;
  if (thread.direct) return { label: t("Direct"), hint: t("Your text runs as this session's own prompt, and its answer comes back here."), kind: "ok" };
  return { label: t("Relayed"), hint: t("Delivered as a message from another session. An older window does not run it as its own prompt."), kind: "warn" };
});
const live = computed(() => props.thread.status === "working");
const subtitle = computed(() => {
  const thread = props.thread;
  switch (thread.status) {
    case "working":
      return t("typing…");
    case "dead":
      return t("stopped");
    case "starting":
      return t("starting…");
    case "stopping":
      return t("stopping…");
    case "offline":
      return t("offline");
    default: {
      const detail = thread.kind === "daemon" ? [thread.model, thread.permission] : [folderName(thread.workspace)];
      return [t("online"), ...detail.filter(Boolean)].join(" · ");
    }
  }
});
</script>

<template>
  <header class="bar chat-head">
    <a class="iconbtn back" :href="href('chats')" :aria-label="t('Back')"><Icon name="back" /></a>
    <button class="chat-who" @click="showInfo(thread)">
      <Avatar :thread="thread" size="sm" />
      <span class="chat-title">
        <b>{{ thread.name }}<span v-if="mode" class="mode" :class="mode.kind" :title="mode.hint">{{ mode.label }}</span></b>
        <span :class="{ live }">{{ subtitle }}</span>
      </span>
    </button>
    <button
      class="iconbtn"
      :aria-pressed="prefs.render === 'source'"
      :title="prefs.render === 'markdown' ? t('Show message source') : t('Render markdown')"
      :aria-label="prefs.render === 'markdown' ? t('Show message source') : t('Render markdown')"
      @click="prefs.render = prefs.render === 'markdown' ? 'source' : 'markdown'"
    >
      <Icon :name="prefs.render === 'markdown' ? 'code' : 'text'" />
    </button>
    <button class="iconbtn" :aria-label="t('More')" @click="showThreadMenu(thread)"><Icon name="more" /></button>
  </header>
</template>

<style>
.bar {
  display: flex; align-items: center; gap: 6px; min-height: 56px; flex: none;
  padding: calc(var(--safe-top) + 6px) 8px 6px calc(var(--safe-left) + 8px);
  background: var(--surface); border-bottom: 1px solid var(--divider);
}
.bar .iconbtn.back { display: none; color: var(--accent); text-decoration: none; }
.chat-who { flex: 1; min-width: 0; display: flex; align-items: center; gap: 10px; padding: 2px 4px; border-radius: 12px; text-align: left; }
.chat-title { min-width: 0; display: flex; flex-direction: column; gap: 1px; }
.mode { margin-left: 8px; padding: 1px 8px; border-radius: 9px; font-size: 0.7rem; font-weight: 600; vertical-align: 2px; }
.mode.ok { background: rgba(79, 174, 78, 0.16); color: var(--ok); }
.mode.warn { background: rgba(232, 150, 12, 0.16); color: var(--warn); }
.mode.bad { background: var(--bad-soft); color: var(--bad); }
.chat-title b { font-size: 1.05rem; font-weight: 650; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chat-title span { font-size: 0.82rem; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chat-title span.live { color: var(--accent); }
@media (max-width: 719px) {
  .bar .iconbtn.back { display: grid; }
}
</style>
