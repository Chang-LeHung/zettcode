<script setup lang="ts">
import { ref } from "vue";
import { gateway } from "../../api/gateway";
import { ApiError } from "../../api/http";
import { t } from "../../i18n";
import { tokens } from "../../lib/format";
import { settings } from "../../stores/config";
import { toast } from "../../stores/ui";
import { confirmAction } from "../sheets/sheets";
import ModelForm from "./ModelForm.vue";

/** Which card is being edited: a model's name, `new` for the form that adds one, or nothing. */
const editing = ref("");

async function remove(name: string): Promise<void> {
  const sure = await confirmAction({
    title: t("Remove {name}?", { name }),
    text: t("It is taken out of the configuration file. A daemon already running keeps using it until it restarts."),
    ok: t("Remove"),
    danger: true,
  });
  if (!sure) return;
  try {
    const reply = await gateway.removeModel(name);
    if (settings.data) settings.data.models = reply.models;
    toast(t("Model removed"));
  } catch (error) {
    toast(error instanceof ApiError ? error.message : String(error), "bad");
  }
}
</script>

<template>
  <p class="card-hint">
    {{ t("Written to the ZettCode configuration file, with its comments kept. A new daemon uses the change; one that is running keeps what it started with.") }}
  </p>
  <template v-for="model in settings.data?.models ?? []" :key="model.name">
    <ModelForm v-if="editing === model.name" :model="model" @done="editing = ''" />
    <div v-else class="card">
      <div class="card-title">{{ model.name }}<template v-if="model.default"> · {{ t("default") }}</template></div>
      <div class="kv"><span>{{ t("Model id") }}</span><span class="mono">{{ model.model }}</span></div>
      <div class="kv"><span>{{ t("Protocol") }}</span><span>{{ model.api }}</span></div>
      <div v-if="model.base_url" class="kv"><span>{{ t("Base URL") }}</span><span class="mono">{{ model.base_url }}</span></div>
      <div class="kv"><span>{{ t("Context") }}</span><span>{{ tokens(model.context_window) }}</span></div>
      <div class="kv"><span>{{ t("Images") }}</span><span>{{ model.multimodal ? t("yes") : t("no") }}</span></div>
      <div v-if="model.web_search" class="kv"><span>{{ t("Web search") }}</span><span>{{ t("yes") }}</span></div>
      <div class="kv"><span>{{ t("Effort levels") }}</span><span>{{ model.efforts.join(", ") || "–" }}</span></div>
      <div class="actions">
        <button class="btn sm ghost" type="button" @click="editing = model.name">{{ t("Edit") }}</button>
        <button
          class="btn sm danger"
          type="button"
          :disabled="(settings.data?.models.length ?? 0) < 2"
          :title="(settings.data?.models.length ?? 0) < 2 ? t('The last model cannot be removed') : ''"
          @click="remove(model.name)"
        >
          {{ t("Remove") }}
        </button>
      </div>
    </div>
  </template>
  <div v-if="settings.data && !settings.data.models.length" class="empty"><b>{{ t("No models") }}</b>{{ t("Add one below.") }}</div>
  <ModelForm v-if="editing === 'new'" @done="editing = ''" />
  <div v-else class="actions"><button class="btn" type="button" @click="editing = 'new'">{{ t("Add a model") }}</button></div>
</template>
