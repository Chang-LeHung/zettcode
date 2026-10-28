<script setup lang="ts">
import { t } from "../../i18n";
import { prefs, type Template } from "../../stores/prefs";
import { applyTemplate, BUILT_IN_TEMPLATES, resetDraft } from "../../stores/spawn";
import { toast } from "../../stores/ui";
import { confirmAction } from "../sheets/sheets";
import SimpleRow from "../common/SimpleRow.vue";
import PaneHeader from "../shell/PaneHeader.vue";

function use(template: Template): void {
  resetDraft();
  applyTemplate(template);
  toast(t("Filled in from {name}", { name: template.label }));
}

async function forget(index: number): Promise<void> {
  const template = prefs.templates[index];
  if (!template) return;
  const sure = await confirmAction({
    title: t("Delete {name}?", { name: template.label }),
    text: t("The template is removed from this browser."),
    ok: t("Delete"),
    danger: true,
  });
  if (sure) prefs.templates.splice(index, 1);
}
</script>

<template>
  <PaneHeader :title="t('New')" />
  <div class="pane-list">
    <div class="pane-group">{{ t("Start from") }}</div>
    <SimpleRow icon="plus" :title="t('Blank')" :subtitle="t('Your defaults')" @click="resetDraft()" />
    <SimpleRow
      v-for="template in BUILT_IN_TEMPLATES"
      :key="template.label"
      icon="bot"
      :title="t(template.label)"
      :subtitle="template.message"
      @click="use(template)"
    />
    <template v-if="prefs.templates.length">
      <div class="pane-group">{{ t("Your templates") }}</div>
      <div v-for="(template, index) in prefs.templates" :key="index" class="template-row">
        <SimpleRow icon="bot" :title="template.label" :subtitle="template.message || template.permission" @click="use(template)" />
        <button class="iconbtn" :aria-label="t('Delete')" @click="forget(index)"><span class="template-x">×</span></button>
      </div>
    </template>
  </div>
</template>

<style>
.template-row { display: flex; align-items: center; }
.template-row .simple-row { flex: 1; min-width: 0; }
.template-x { font-size: 1.4rem; line-height: 1; }
</style>
