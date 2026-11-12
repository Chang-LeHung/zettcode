<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { gateway } from "../../api/gateway";
import { ApiError } from "../../api/http";
import { t } from "../../i18n";
import { loadConfig } from "../../stores/config";
import { prefs, rememberWorkspace } from "../../stores/prefs";
import { go } from "../../stores/route";
import { draft, resetDraft } from "../../stores/spawn";
import { loadThreads } from "../../stores/threads";
import { toast } from "../../stores/ui";
import type { SpawnForm } from "../../types";
import PageBar from "../common/PageBar.vue";
import { confirmAction } from "../sheets/sheets";
import ExternalAgentForm from "./ExternalAgentForm.vue";
import SpawnExtra from "./SpawnExtra.vue";
import SpawnModel from "./SpawnModel.vue";
import SpawnShell from "./SpawnShell.vue";
import SpawnTemplates from "./SpawnTemplates.vue";
import SpawnWhere from "./SpawnWhere.vue";

const busy = ref(false);
const mode = ref<"daemon" | "agent">("daemon");
const failure = ref<ApiError | null>(null);
const ready = computed(() => draft.workspace.trim() !== "" && !busy.value);

onMounted(() => void loadConfig());

function payload(): Partial<SpawnForm> {
  const body: Partial<SpawnForm> = { workspace: draft.workspace.trim(), permission: draft.permission };
  for (const key of ["model", "effort", "name", "resume", "message"] as const) {
    const value = draft[key].trim();
    if (value) body[key] = value;
  }
  return body;
}

async function start(): Promise<void> {
  // Full is the one level with no sandbox and nobody to approve a command, so it is started on purpose, with the
  // settings it will run with in front of the person.
  if (
    draft.permission === "full" &&
    !(await confirmAction({
      title: t("Start with full access?"),
      text: t("It will run commands as you in {folder}, with no sandbox and nobody to approve them. Model: {model}.", {
        folder: draft.workspace.trim(),
        model: draft.model || t("Default"),
      }),
      ok: t("Start daemon"),
      danger: true,
    }))
  )
    return;
  busy.value = true;
  failure.value = null;
  try {
    const made = await gateway.spawn(payload());
    rememberWorkspace(made.thread?.workspace ?? draft.workspace.trim());
    await loadThreads();
    if (made.first && !made.first.ok) toast(made.first.error?.message ?? t("The first message was not sent"), "bad");
    else toast(t("Daemon started"));
    resetDraft();
    go("chats", made.thread?.id ?? "");
  } catch (error) {
    failure.value = error instanceof ApiError ? error : new ApiError(0, { message: String(error) });
  } finally {
    busy.value = false;
  }
}

function saveTemplate(): void {
  const label = draft.name.trim() || t("Template {number}", { number: prefs.templates.length + 1 });
  prefs.templates.push({
    label,
    name: draft.name,
    model: draft.model,
    effort: draft.effort,
    permission: draft.permission,
    message: draft.message,
  });
  toast(t("Saved as a template"));
}
</script>

<template>
  <PageBar :title="mode === 'daemon' ? t('Start a daemon') : t('Start an external agent')" />
  <div class="page">
    <div class="page-inner">
      <div class="new-mode" role="tablist" :aria-label="t('What to start')">
        <button type="button" :class="{ on: mode === 'daemon' }" role="tab" :aria-selected="mode === 'daemon'" @click="mode = 'daemon'">
          {{ t("Daemon") }}
        </button>
        <button type="button" :class="{ on: mode === 'agent' }" role="tab" :aria-selected="mode === 'agent'" @click="mode = 'agent'">
          {{ t("External agent") }}
        </button>
      </div>
    <form v-if="mode === 'daemon'" class="new-form" @submit.prevent="start">
      <SpawnTemplates />
      <SpawnWhere />
      <SpawnModel />
      <SpawnShell />
      <SpawnExtra />
      <div v-if="failure" class="errcard" role="alert">
        <b>{{ t("It did not start.") }}</b> {{ failure.message }}
      </div>
      <button class="btn block" type="submit" :disabled="!ready">
        <span v-if="busy" class="spin" />
        {{ busy ? t("Starting… this can take a few seconds") : t("Start daemon") }}
      </button>
      <div class="actions">
        <button class="btn sm ghost" type="button" @click="saveTemplate">{{ t("Save as template") }}</button>
        <button class="btn sm ghost" type="button" @click="resetDraft()">{{ t("Clear") }}</button>
      </div>
    </form>
    <ExternalAgentForm v-else />
    </div>
  </div>
</template>

<style>
.new-mode { display: flex; gap: 4px; max-width: 360px; margin: 4px auto 14px; padding: 4px; border: 1px solid var(--divider); border-radius: 12px; background: var(--surface-2); }
.new-mode button { flex: 1; min-height: 36px; border-radius: 9px; color: var(--muted); font-weight: 600; font-size: 0.9rem; }
.new-mode button.on { background: var(--surface); color: var(--text); box-shadow: 0 2px 8px rgba(31, 45, 61, 0.1); }
</style>
