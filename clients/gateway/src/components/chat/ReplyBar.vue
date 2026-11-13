<script setup lang="ts">
import { t } from "../../i18n";
import Icon from "../common/Icon.vue";

/** The message being replied to, above the input, as a messenger shows it: who, a line of what they said, and a way to drop it. */
defineProps<{ who: string; text: string }>();
defineEmits<{ cancel: [] }>();
</script>

<template>
  <div class="replybar" role="group" :aria-label="t('Replying to')">
    <Icon name="reply" size="sm" class="replybar-icon" />
    <div class="replybar-body">
      <strong class="replybar-who">{{ who ? t("Reply to {name}", { name: who }) : t("Reply to your message") }}</strong>
      <span class="replybar-text">{{ text }}</span>
    </div>
    <button type="button" class="iconbtn" :aria-label="t('Cancel reply')" :title="t('Cancel reply')" @pointerdown.prevent @click="$emit('cancel')">
      <Icon name="close" size="sm" />
    </button>
  </div>
</template>

<style scoped>
.replybar { flex: none; display: flex; align-items: center; gap: 10px; padding: 8px calc(var(--safe-right) + 12px) 8px calc(var(--safe-left) + 14px); background: var(--surface); border-top: 1px solid var(--divider); }
.replybar-icon { color: var(--accent); flex: none; }
.replybar-body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 1px; border-left: 3px solid var(--accent); padding-left: 10px; }
.replybar-who { font-size: 0.82rem; color: var(--accent); font-weight: 600; }
.replybar-text { font-size: 0.86rem; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
</style>
