<script setup lang="ts">
import { t } from "../../i18n";
import { prefs, type Template } from "../../stores/prefs";
import { applyTemplate, BUILT_IN_TEMPLATES, resetDraft } from "../../stores/spawn";
</script>

<template>
  <div class="spawn-templates">
    <div class="spawn-templates-label">{{ t("Start from") }}</div>
    <div class="chips">
      <button type="button" class="chip" @click="resetDraft()">{{ t("Blank") }}</button>
      <button v-for="template in [...BUILT_IN_TEMPLATES, ...prefs.templates]" :key="template.label" type="button" class="chip" @click="applyTemplate(template as Template)">
        {{ t(template.label) }}
      </button>
    </div>
  </div>
</template>

<style>
/* A wide screen lists the templates in the pane beside the form. */
@media (min-width: 720px) {
  .spawn-templates { display: none; }
}
.spawn-templates-label { padding: 8px 4px 0; color: var(--muted); font-size: 0.76rem; font-weight: 650; letter-spacing: 0.03em; text-transform: uppercase; }
.spawn-templates .chips { padding: 6px 4px 0; flex-wrap: wrap; }
</style>
