<script setup lang="ts">
// Which gateway this device is talking to. The page the gateway serves has one answer and cannot change it; the app
// keeps a list, and going back to it is the app's sign-out.

import { t } from "../../i18n";
import { disconnectServer, servers } from "../../stores/servers";
</script>

<template>
  <template v-if="servers.mode === 'app'">
    <div class="card">
      <div class="kv"><span>{{ t("Server") }}</span><span>{{ servers.active?.name ?? "–" }}</span></div>
      <div class="kv"><span>{{ t("Address") }}</span><span class="mono">{{ servers.active?.url ?? "–" }}</span></div>
      <div class="actions">
        <button class="btn ghost" type="button" @click="disconnectServer">{{ t("Switch server") }}</button>
      </div>
    </div>
    <p class="card-hint">{{ t("The token stays on this device. Switching reloads the page, so nothing from one gateway is drawn beside another's.") }}</p>
  </template>
  <p v-else class="card-hint">
    {{ t("This page was served by one gateway. The desktop and mobile apps keep a list of them.") }}
  </p>
</template>
