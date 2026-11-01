<script setup lang="ts">
import { t } from "../../i18n";
import { prefs } from "../../stores/prefs";
import Segmented from "../common/Segmented.vue";
import ProfileCard from "./ProfileCard.vue";
</script>

<template>
  <ProfileCard />
  <div class="card">
    <div class="card-title">{{ t("Theme") }}</div>
    <Segmented v-model="prefs.theme" :label="t('Theme')" :options="[{ value: 'auto', label: t('System') }, { value: 'light', label: t('Light') }, { value: 'dark', label: t('Dark') }]" />
    <div class="card-title">{{ t("Text size") }}</div>
    <Segmented v-model="prefs.size" :label="t('Text size')" :options="[{ value: 's', label: t('Small') }, { value: 'm', label: t('Medium') }, { value: 'l', label: t('Large') }]" />
    <div class="card-title">{{ t("Messages") }}</div>
    <Segmented v-model="prefs.render" :label="t('Messages')" :options="[{ value: 'markdown', label: t('Rendered') }, { value: 'source', label: t('Source') }]" />
    <p class="card-hint">{{ t("Rendered shows markdown with highlighted code and typeset math. Source shows the text exactly as it was written.") }}</p>
    <div class="card-title">{{ t("Language") }}</div>
    <Segmented v-model="prefs.language" :label="t('Language')" :options="[{ value: 'en', label: 'English' }, { value: 'zh', label: '中文' }]" />
  </div>
</template>
