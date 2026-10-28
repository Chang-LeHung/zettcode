<script setup lang="ts">
import { t } from "../../i18n";
import { prefs, type Template } from "../../stores/prefs";
import { applyTemplate, BUILT_IN_TEMPLATES } from "../../stores/spawn";
</script>

<template>
  <div class="spawn-templates">
    <div class="chips">
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
.spawn-templates .chips { padding: 8px 4px 0; }
</style>
