<script setup lang="ts">
import { computed } from "vue";
import { t } from "../../i18n";
import { settings } from "../../stores/config";
import { draft } from "../../stores/spawn";
import Segmented from "../common/Segmented.vue";

const allowFull = computed(() => settings.data?.allow_full === true);
const options = computed(() => [
  { value: "deny", label: t("No shell") },
  { value: "safe", label: t("Sandboxed") },
  { value: "full", label: t("Full"), disabled: !allowFull.value },
]);
const hint = computed(
  () =>
    ({
      deny: t("It can read and edit files and talk, but never runs a command."),
      safe: t("Every command runs in a sandbox: it writes only the workspace, credentials are hidden, the network is open."),
      full: t("Commands run with your account's full access: no sandbox, no approval, no network limit."),
    })[draft.permission] ?? "",
);
</script>

<template>
  <div class="card">
    <div class="card-title">{{ t("Shell access") }}</div>
    <Segmented v-model="draft.permission" :options="options" :label="t('Shell access')" />
    <p class="card-hint" :class="{ warn: draft.permission === 'full' }">{{ hint }}</p>
    <p v-if="!allowFull" class="card-hint">{{ t("Full access is turned off. It was started with --no-full.") }}</p>
    <p class="card-hint">{{ t("A daemon never asks anyone: there is nobody to approve a command.") }}</p>
  </div>
</template>
