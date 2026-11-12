<script setup lang="ts">
import { t } from "../../i18n";
import { go } from "../../stores/route";
</script>

<template>
  <div class="welcome">
    <img src="/static/logo.svg" alt="" width="84" height="84" />
    <b>{{ t("Pick a conversation") }}</b>
    <span>{{ t("Choose a session on the left, or start a new one.") }}</span>
    <button class="btn" @click="go('new')">{{ t("New session") }}</button>
  </div>
</template>

<style>
.welcome { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; padding: 24px; text-align: center; color: var(--muted); background: radial-gradient(700px 420px at 50% 40%, var(--accent-soft), transparent 70%); }
.welcome img { object-fit: contain; filter: drop-shadow(0 12px 24px rgba(31, 45, 61, 0.16)); }
.welcome b { color: var(--text); font-size: 1.4rem; letter-spacing: -0.03em; }
.welcome span { max-width: 24rem; line-height: 1.5; }
.welcome .btn { margin-top: 8px; box-shadow: 0 10px 24px rgba(47, 124, 246, 0.25); }
</style>
