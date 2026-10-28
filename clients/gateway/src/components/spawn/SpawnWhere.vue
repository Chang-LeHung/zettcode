<script setup lang="ts">
import { t } from "../../i18n";
import { prefs } from "../../stores/prefs";
import { draft } from "../../stores/spawn";
import { openSheet } from "../../stores/ui";
import Icon from "../common/Icon.vue";
import FolderPicker from "./FolderPicker.vue";

async function browse(): Promise<void> {
  const chosen = await openSheet<string>(t("Choose a folder"), FolderPicker, { start: draft.workspace });
  if (chosen) draft.workspace = chosen;
}
</script>

<template>
  <div class="card">
    <div class="card-title">{{ t("Where") }}</div>
    <div class="field-row">
      <label for="spawn-workspace">{{ t("Workspace") }}</label>
      <input
        id="spawn-workspace"
        v-model="draft.workspace"
        type="text"
        inputmode="url"
        autocapitalize="off"
        autocomplete="off"
        spellcheck="false"
        :placeholder="t('/path/to/project')"
      />
      <button class="iconbtn" type="button" :aria-label="t('Choose a folder')" @click="browse"><Icon name="folder" /></button>
    </div>
    <div v-if="prefs.recent.length" class="chips">
      <button v-for="path in prefs.recent" :key="path" type="button" class="chip" @click="draft.workspace = path">
        {{ path }}
      </button>
    </div>
    <p class="card-hint">{{ t("The agent reads and changes files here. Any folder on the machine the gateway runs on can be chosen, unless it was started with --root.") }}</p>
  </div>
</template>

<style>
.chips { display: flex; flex-wrap: wrap; gap: 6px; padding: 4px 16px 12px; }
.chip { max-width: 100%; padding: 5px 11px; border-radius: 14px; background: var(--surface-2); font-size: 0.84rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chip:hover { background: var(--accent-soft); }
</style>
