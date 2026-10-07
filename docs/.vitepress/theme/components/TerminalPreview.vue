<script setup lang="ts">
import { withBase } from "vitepress";

defineProps<{ alt: string; caption: string }>();
</script>

<template>
  <figure class="terminal-preview">
    <div class="terminal-window" tabindex="0" :aria-label="alt">
      <div class="terminal-titlebar" aria-hidden="true">
        <span class="terminal-lights"><i></i><i></i><i></i></span>
        <span>zettcode <span class="terminal-path">— ~/projects/api</span></span>
        <span class="terminal-title-end">UTF-8</span>
      </div>
      <div class="terminal-scroll">
        <img :src="withBase('/terminal.svg')" :alt="alt" width="1000" height="800" loading="eager" />
      </div>
    </div>
    <figcaption>{{ caption }}</figcaption>
  </figure>
</template>
