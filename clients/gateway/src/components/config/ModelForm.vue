<script setup lang="ts">
import { computed, reactive, ref } from "vue";
import { gateway } from "../../api/gateway";
import { ApiError } from "../../api/http";
import { t } from "../../i18n";
import { blankDraft, changesOf, draftOf, EFFORT_LEVELS, entryOf, problem, toggled } from "../../lib/modelForm";
import { settings } from "../../stores/config";
import { toast } from "../../stores/ui";
import type { ModelOption } from "../../types";
import Segmented from "../common/Segmented.vue";
import SwitchRow from "../common/SwitchRow.vue";

/** The model being changed, or nothing when a new one is being written. */
const props = defineProps<{ model?: ModelOption }>();
const emit = defineEmits<{ done: [] }>();

const draft = reactive(props.model ? draftOf(props.model) : blankDraft());
const busy = ref(false);
const failure = ref("");
const showToken = ref(false);
const protocols = computed(() => [
  { value: "chat", label: t("Chat") },
  { value: "responses", label: t("Responses") },
  { value: "anthropic", label: "Anthropic" },
]);
const mistake = computed(() => problem(draft));
const changes = computed(() => (props.model ? changesOf(draft, props.model) : null));
const nothing = computed(() => changes.value !== null && Object.keys(changes.value).length === 0);

async function save(): Promise<void> {
  if (mistake.value) {
    failure.value = t(mistake.value);
    return;
  }
  busy.value = true;
  failure.value = "";
  try {
    const reply = props.model
      ? await gateway.changeModel(props.model.name, changes.value ?? {})
      : await gateway.addModel(entryOf(draft));
    if (settings.data) settings.data.models = reply.models;
    toast(props.model ? t("Model saved") : t("Model added"));
    emit("done");
  } catch (error) {
    failure.value = error instanceof ApiError ? error.message : String(error);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <form class="card model-form" @submit.prevent="save">
    <div class="card-title">{{ model ? t("Edit {name}", { name: model.name }) : t("Add a model") }}</div>
    <div class="field-row">
      <label for="mf-model">{{ t("Model id") }}</label>
      <input id="mf-model" v-model="draft.model" required autocomplete="off" spellcheck="false" placeholder="gpt-4.1" />
    </div>
    <div class="field-row">
      <label for="mf-name">{{ t("Shown as") }}</label>
      <input id="mf-name" v-model="draft.display_model" autocomplete="off" :placeholder="t('Same as the model id')" />
    </div>
    <div class="card-title">{{ t("Protocol") }}</div>
    <Segmented v-model="draft.api" :options="protocols" :label="t('Protocol')" />
    <div class="field-row">
      <label for="mf-url">{{ t("Base URL") }}</label>
      <input id="mf-url" v-model="draft.base_url" type="url" autocomplete="off" spellcheck="false" :placeholder="t('The protocol’s own address')" />
    </div>
    <div class="field-row">
      <label for="mf-token">{{ t("API key") }}</label>
      <input
        id="mf-token"
        v-model="draft.token"
        :type="showToken ? 'text' : 'password'"
        autocomplete="new-password"
        spellcheck="false"
        :placeholder="model ? t('Leave empty to keep the saved key') : t('Or set it in the environment')"
      />
      <button class="btn sm ghost" type="button" @click="showToken = !showToken">{{ showToken ? t("Hide") : t("Show") }}</button>
    </div>
    <div class="field-row">
      <label for="mf-window">{{ t("Context") }}</label>
      <input id="mf-window" v-model="draft.context_window" inputmode="numeric" autocomplete="off" placeholder="128000" />
    </div>
    <div class="field-row">
      <label for="mf-compact">{{ t("Compact at") }}</label>
      <input id="mf-compact" v-model="draft.compact_percent" inputmode="decimal" autocomplete="off" placeholder="80" />
      <span class="unit">%</span>
    </div>
    <div class="field-row">
      <label for="mf-temp">{{ t("Temperature") }}</label>
      <input id="mf-temp" v-model="draft.temperature" inputmode="decimal" autocomplete="off" :placeholder="t('Provider default')" />
    </div>
    <SwitchRow v-model="draft.multimodal" :label="t('Accepts images')" />
    <SwitchRow v-model="draft.web_search" :label="t('Web search')" :hint="t('The provider searches the web for the model.')" />
    <div class="card-title">{{ t("Effort levels") }}</div>
    <div class="levels" role="group" :aria-label="t('Effort levels')">
      <button
        v-for="level in EFFORT_LEVELS"
        :key="level"
        type="button"
        class="level"
        :aria-pressed="draft.efforts.includes(level)"
        @click="draft.efforts = toggled(draft.efforts, level)"
      >
        {{ level }}
      </button>
    </div>
    <p class="card-hint">{{ t("Choose none to allow every level.") }}</p>
    <p v-if="failure" class="errcard" role="alert">{{ failure }}</p>
    <div class="actions">
      <button class="btn sm" type="submit" :disabled="busy || nothing">
        <span v-if="busy" class="spin" /> {{ model ? t("Save") : t("Add model") }}
      </button>
      <button class="btn sm ghost" type="button" @click="emit('done')">{{ t("Cancel") }}</button>
    </div>
  </form>
</template>

<style>
.model-form .unit { color: var(--muted); }
.levels { display: flex; gap: 6px; flex-wrap: wrap; padding: 4px 16px 8px; }
.level { min-height: 32px; padding: 0 12px; border-radius: 16px; background: var(--surface-2); color: var(--muted); font-size: 0.88rem; transition: background 0.2s, color 0.2s; }
.level[aria-pressed="true"] { background: var(--accent); color: var(--accent-text); }
.model-form .errcard { margin: 6px 16px; }
</style>
