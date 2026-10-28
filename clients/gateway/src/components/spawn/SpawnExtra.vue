<script setup lang="ts">
import { t } from "../../i18n";
import { draft } from "../../stores/spawn";
import Icon from "../common/Icon.vue";
</script>

<template>
  <div class="card">
    <div class="card-title">{{ t("About it") }}</div>
    <div class="field-row">
      <label for="spawn-name">{{ t("Name") }}</label>
      <input id="spawn-name" v-model="draft.name" type="text" maxlength="40" autocomplete="off" :placeholder="t('What it is for')" />
    </div>
    <div v-if="draft.resume" class="field-row">
      <label>{{ t("Continues") }}</label>
      <span class="mono spawn-resume">{{ draft.resume }}</span>
      <button class="iconbtn" type="button" :aria-label="t('Start an empty conversation instead')" @click="draft.resume = ''">
        <Icon name="close" size="sm" />
      </button>
    </div>
    <div class="field-row stack">
      <label for="spawn-message">{{ t("First message") }}</label>
      <textarea id="spawn-message" v-model="draft.message" rows="3" :placeholder="t('Optional. Sent as soon as it is up.')" />
    </div>
  </div>
</template>

<style>
.spawn-resume { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
