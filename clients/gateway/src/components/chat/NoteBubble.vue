<script setup lang="ts">
import { t } from "../../i18n";

defineProps<{ text: string }>();
</script>

<template>
  <details class="note">
    <summary>{{ t("Earlier conversation summarized") }}</summary>
    <p>{{ text }}</p>
  </details>
</template>

<style>
.note { align-self: center; max-width: 92%; margin: 8px 0; padding: 4px 12px; border-radius: 14px; background: rgba(0, 0, 0, 0.28); color: #fff; font-size: 0.8rem; text-align: center; }
.note summary { cursor: pointer; list-style: none; }
.note summary::-webkit-details-marker { display: none; }
.note p { margin: 6px 0 2px; text-align: left; white-space: pre-wrap; }
</style>
