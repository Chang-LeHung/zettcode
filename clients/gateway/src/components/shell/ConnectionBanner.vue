<script setup lang="ts">
import { computed } from "vue";
import { t } from "../../i18n";
import { lobby } from "../../stores/threads";

const message = computed(() => {
  if (!lobby.live) return { text: t("Connecting…"), bad: false, spin: true };
  if (lobby.status?.broker.reachable === false) {
    return { text: t("The session broker is not connected, so nobody can be reached"), bad: true, spin: false };
  }
  return null;
});
</script>

<template>
  <div v-if="message" class="banner" :class="{ bad: message.bad }" role="status">
    <span v-if="message.spin" class="spin" />
    <span>{{ message.text }}</span>
  </div>
</template>

<style>
.banner {
  display: flex; align-items: center; gap: 8px; margin: 0 12px 8px; padding: 8px 12px; border-radius: 12px;
  background: var(--accent-soft); color: var(--text); font-size: 0.88rem;
}
.banner.bad { background: var(--bad-soft); }
.banner .spin { width: 14px; height: 14px; border-width: 2px; }
</style>
