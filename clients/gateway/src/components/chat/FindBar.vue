<script setup lang="ts">
import { nextTick, onMounted, ref } from "vue";
import { t } from "../../i18n";
import { chat } from "../../stores/chat";
import { closeFind, find, step } from "../../stores/chatSearch";
import Icon from "../common/Icon.vue";

const input = ref<HTMLInputElement | null>(null);
onMounted(() => void nextTick(() => input.value?.focus()));

// The newest match first, so Enter goes back through the conversation and Shift+Enter forward again.
function onKey(event: KeyboardEvent): void {
  if (event.key === "Enter" && !event.isComposing) {
    event.preventDefault();
    step(event.shiftKey ? 1 : -1);
  } else if (event.key === "Escape") {
    event.stopPropagation();
    closeFind();
  }
}
</script>

<template>
  <div class="findbar" role="search">
    <Icon name="search" size="sm" />
    <input
      ref="input"
      v-model="find.query"
      type="search"
      autocomplete="off"
      :placeholder="t('Find in this conversation')"
      :aria-label="t('Find in this conversation')"
      @keydown="onKey"
    />
    <span v-if="chat.loadingEarlier" class="spin" :aria-label="t('Loading…')" />
    <span v-else-if="find.query.trim()" class="find-count" aria-live="polite">
      {{ find.keys.length ? `${find.at + 1} / ${find.keys.length}` : t("No matches") }}
    </span>
    <button class="iconbtn" type="button" :disabled="!find.keys.length" :aria-label="t('Older match')" :title="t('Older match')" @click="step(-1)">
      <Icon name="up" size="sm" />
    </button>
    <button class="iconbtn" type="button" :disabled="!find.keys.length" :aria-label="t('Newer match')" :title="t('Newer match')" @click="step(1)">
      <Icon name="down" size="sm" />
    </button>
    <button class="iconbtn" type="button" :aria-label="t('Close')" @click="closeFind"><Icon name="close" size="sm" /></button>
  </div>
</template>

<style>
.findbar {
  flex: none; display: flex; align-items: center; gap: 4px; padding: 4px 8px 4px 14px;
  background: var(--surface); border-bottom: 1px solid var(--divider); color: var(--muted); animation: unfold 0.18s ease-out;
}
.findbar input { flex: 1; min-width: 0; height: 36px; border: 0; outline: 0; background: none; color: var(--text); font-size: 1rem; }
.findbar input::-webkit-search-cancel-button { display: none; }
.findbar .spin { width: 14px; height: 14px; border-width: 2px; }
.find-count { flex: none; font-size: 0.82rem; font-variant-numeric: tabular-nums; }
.findbar .iconbtn { width: 36px; height: 36px; }
.findbar .iconbtn:disabled { opacity: 0.35; }
</style>
