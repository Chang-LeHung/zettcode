<script setup lang="ts">
import { t } from "../../i18n";
import { auth, signOut } from "../../stores/auth";
import { lobby } from "../../stores/threads";
</script>

<template>
  <div class="card">
    <div class="kv"><span>{{ t("Gateway") }}</span><span>{{ lobby.status?.version ?? "–" }}</span></div>
    <div class="kv"><span>{{ t("Live updates") }}</span><span>{{ lobby.live ? t("connected") : t("reconnecting") }}</span></div>
    <div class="kv"><span>{{ t("Session broker") }}</span><span>{{ lobby.status?.broker.reachable ? t("connected") : t("not connected") }}</span></div>
    <div class="kv"><span>{{ t("This gateway is") }}</span><span class="mono">{{ lobby.status?.gateway.id ?? "–" }}</span></div>
    <div class="kv"><span>{{ t("Handle") }}</span><span class="mono">@{{ lobby.status?.gateway.handle }}</span></div>
  </div>
  <p v-if="auth.open" class="card-hint">{{ t("This gateway has no token: anyone on this machine can start agents that run commands as you.") }}</p>
  <p v-else class="card-hint">{{ t("Anyone signed in here can start agents that run commands as you. Keep the token private.") }}</p>
  <div v-if="!auth.open" class="actions"><button class="btn danger" @click="signOut">{{ t("Sign out") }}</button></div>
</template>
