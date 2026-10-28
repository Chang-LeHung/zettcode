<script setup lang="ts">
import { t } from "../../i18n";

defineProps<{ text: string; ok: string; danger?: boolean }>();
const emit = defineEmits<{ close: [answer: boolean] }>();
</script>

<template>
  <p class="card-hint confirm-text">{{ text }}</p>
  <div class="actions">
    <button class="btn" :class="{ danger }" @click="emit('close', true)">{{ ok }}</button>
    <button class="btn ghost" @click="emit('close', false)">{{ t("Cancel") }}</button>
  </div>
</template>

<style>
.confirm-text { padding-top: 8px; font-size: 0.95rem; color: var(--text); }
</style>
