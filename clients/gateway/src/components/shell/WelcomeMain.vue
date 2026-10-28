<script setup lang="ts">
import { t } from "../../i18n";
import { go } from "../../stores/route";
</script>

<template>
  <div class="welcome">
    <img src="/static/logo.svg" alt="" width="84" height="84" />
    <b>{{ t("Pick a conversation") }}</b>
    <span>{{ t("Choose a session on the left, or start a new daemon.") }}</span>
    <button class="btn" @click="go('new')">{{ t("New daemon") }}</button>
  </div>
</template>

<style>
.welcome { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; padding: 24px; text-align: center; color: var(--muted); background: var(--surface-2); }
.welcome img { object-fit: contain; }
.welcome b { color: var(--text); font-size: 1.15rem; }
</style>
